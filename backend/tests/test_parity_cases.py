"""เกณฑ์ A ส่วนเพิ่ม: กรณีที่ oracle หลัก (ค่าเริ่มต้น) ไม่ครอบคลุม — ชุดตัวแปรที่คณะวิจัยปรับได้ และ failure paths

ฝั่งเดิมรันโค้ดต้นฉบับที่ root ของ workspace (7bf84e4; ก่อน 10 ต.ค. คือ e6aee03) จริงใน process เดียวกัน runtime เดียวกัน:
- TFP.py โหลดจากไฟล์ต้นฉบับเป็นโมดูลชื่อ tfp_original_source (ไม่ลงทะเบียนชื่อ TFP)
- ฟังก์ชันจาก TFP_App1.3.0.py และ data_loader.py exec จาก AST แบบเดียวกับ oracle (ถอดเฉพาะ st.cache_data)
- สูตร scenario รันบล็อก if/elif/else ของแดชบอร์ดนำเสนอ (5830-5837) จากไฟล์แอปตรง ๆ
ฝั่งใหม่เรียก backend/app เทียบผลแบบ canonical (float.hex) หรือชนิด+ข้อความของ exception ให้ตรงทุกค่า
ไม่มี expected ที่เขียนเอง ผลอ้างอิงคือผลของโค้ดต้นฉบับในรอบเดียวกัน
"""
import ast
import importlib.util
import itertools
import math
import re
import sys
import time
import warnings
from typing import Optional

import gspread
import numpy as np
import pandas as pd
import pytest
from google.oauth2.service_account import Credentials
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller

import parity
from app import data_loader
from app.modeling import core, scenario, tfp

fingerprint, replay = parity.fingerprint, parity.replay
REPO = parity.REPO
sys.path.insert(0, str(REPO / "tools" / "refactor"))
from extract_core import CORE  # noqa: E402  รายชื่อสิ่งที่ย้าย (test_moved_source ตรวจว่าเป็นโค้ดเดิม)
SHOCKS = [1.0, 5.0, -2.5, 0.1, 0.0, -50.0, 20.0]


def exec_nodes(path, names, ns, strip=()):
    src = path.read_text(encoding="utf-8")
    nodes = []
    for n in ast.parse(src).body:
        name = n.name if isinstance(n, ast.FunctionDef) else (
            n.targets[0].id if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) else None)
        if name in names:
            if isinstance(n, ast.FunctionDef):
                assert all(name in strip and ast.unparse(d) == "st.cache_data(show_spinner=False)"
                           for d in n.decorator_list), name
                n.decorator_list = []
            nodes.append(n)
    assert sorted(names) == sorted({getattr(n, "name", None) or n.targets[0].id for n in nodes})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    return ns


def load_original():
    spec = importlib.util.spec_from_file_location("tfp_original_source", REPO / "TFP.py")
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    F = exec_nodes(REPO / "TFP_App1.3.0.py", CORE, {
        "np": np, "pd": pd, "re": re, "math": math, "warnings": warnings, "ARIMA": ARIMA,
        "adfuller": adfuller, "ConvergenceWarning": ConvergenceWarning,
        # _build_adf_detail_table (7bf84e4) ใช้ชื่อที่แอป import จาก TFP — ใช้ของ TFP.py ต้นฉบับ
        "adf_report": T.adf_report, "ADF_DIFF_TREND": T.ADF_DIFF_TREND, "CANDIDATE_VARS": T.CANDIDATE_VARS,
        "Optional": Optional},  # 4c8aa71: annotation ของ _run_rolling_backtest (แอป :89)
        strip=("_auto_arima_forecast", "_run_backtest", "_run_rolling_backtest"))  # st.cache_data มีผลแค่ cache
    loader_names = ["SHEET_ID", "SCOPES", "DATA_TAB", "RESEARCHER_TAB", "_RETRYABLE_STATUS_CODES",
                    "_call_with_retry", "_extract_sheet_id", "_load_researcher_rdh", "load_data_gsheet"]
    L = exec_nodes(REPO / "data_loader.py", loader_names, {
        "re": re, "time": time, "Optional": Optional, "gspread": gspread, "Credentials": Credentials, "pd": pd,
        "RAW_TO_MODEL": T.RAW_TO_MODEL, "PERCENT_VARS": T.PERCENT_VARS, "RDH_SOURCE": T.RDH_SOURCE})

    src = (REPO / "TFP_App1.3.0.py").read_text(encoding="utf-8")
    block = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.If) and ast.unparse(n.test) == "scenario_var.startswith('ln_')"]
    assert len(block) == 1
    code = compile(ast.Module(body=block, type_ignores=[]), "TFP_App1.3.0.py", "exec")

    def scenario_inline(var, coef, shock):
        ns = {"scenario_var": var, "_coef": coef, "scenario_shock": shock, "math": math,
              "_PCT_SCALED_VARS": F["_PCT_SCALED_VARS"]}
        exec(code, ns)
        return ns["scenario_pct_effect"]

    return {"T": T, "F": F, "L": L, "scenario": scenario_inline}


def load_new():
    return {"T": tfp, "F": vars(core), "L": vars(data_loader), "scenario": scenario.scenario_pct_effect}


def load_df_raw():
    tabs = replay.load_tabs()
    real = data_loader._get_client
    data_loader._get_client = lambda: replay._FakeClient(tabs)
    try:
        return data_loader.load_data_gsheet()
    finally:
        data_loader._get_client = real


@pytest.fixture(scope="module")
def original():
    return load_original()


@pytest.fixture(scope="module")
def new():
    return load_new()


@pytest.fixture(scope="module")
def df_raw():
    return load_df_raw()


def outcome(fn, *args, **kwargs):
    try:
        return ["ok", fingerprint.canonical(fn(*args, **kwargs))]
    except Exception as e:  # เทียบชนิดและข้อความของ error ด้วย
        return ["error", type(e).__name__, str(e)]


def pipeline(side, df_raw, lr_vars, sr_spec):
    """ลำดับเดียวกับหน้าเว็บเดิม TFP_App1.3.0.py:3309-3341 แล้วต่อ influence (5990) และ scenario"""
    T, F = side["T"], side["F"]
    out = {}
    model_df = T.build_model_frame(df_raw)
    dep_ln = "ln_" + T.DEP_VAR
    try:
        lr_res, lr_resid = T.run_long_run(model_df, dep_ln, lr_vars)
        sr_res = T.run_short_run(model_df, dep_ln, sr_spec, lr_resid)
    except Exception as e:
        out["error"] = [type(e).__name__, str(e)]
        return out
    out["lr"] = fingerprint.canonical([lr_res.params, lr_res.bse, lr_res.pvalues, lr_resid])
    if sr_res is None:  # หน้าเดิมแสดง error และไม่คำนวณตาราง/การ์ดต่อ
        out["sr"] = None
        return out
    out["sr"] = fingerprint.canonical([sr_res.params, sr_res.bse, sr_res.pvalues])
    lr_table, sr_table = T.build_coefficient_tables(lr_res, sr_res)
    out["combined_table"] = outcome(F["_merge_coefficient_tables"], lr_table, sr_table)
    lr_raw = F["_extract_raw_coefficients"](F["_unrounded_coefficient_table"](lr_res))
    sr_raw = F["_extract_raw_coefficients"](F["_unrounded_coefficient_table"](sr_res))
    out["raw_maps"] = fingerprint.canonical([lr_raw, sr_raw])

    def diag_display():
        d = T.run_diagnostics(model_df, dep_ln, lr_vars, lr_res, sr_res, lr_resid, short_run_spec=sr_spec)
        shown = d.copy()
        shown["รายการ"] = shown["รายการ"].apply(F["var_label_with_abbr"])
        return shown

    out["diag_display"] = outcome(diag_display)
    # ตาราง ADF รายตัวแปรต่อจาก diagnostics (7bf84e4 TFP_App1.3.0.py:3387-3391)
    out["adf_detail"] = outcome(F["_build_adf_detail_table"], model_df, dep_ln, lr_vars, sr_spec)
    out["influence"] = outcome(F["_compute_influence_df"], model_df, dep_ln, lr_vars, lr_raw)
    out["scenario"] = fingerprint.canonical(
        {v: [side["scenario"](v, lr_raw[v]["coef"], s) for s in SHOCKS] for v in lr_vars if v in lr_raw})
    return out


LR = list(tfp.LONG_RUN_VARS)
SR = list(tfp.SHORT_RUN_SPEC)
VAR_SETS = (
    [(f"lr={'+'.join(c)}", list(c), SR) for k in range(1, len(LR)) for c in itertools.combinations(LR, k)]
    + [(f"sr-ไม่มี-{b}", LR, [s for s in SR if s[0] != b]) for b, _, _ in SR]
    + [("lr-ว่าง", [], SR), ("sr-ว่าง", LR, []), ("sr-เหลือ-1", LR, SR[:1])]
)


@pytest.mark.parametrize("name,lr_vars,sr_spec", VAR_SETS, ids=[c[0] for c in VAR_SETS])
def test_variable_sets(original, new, df_raw, name, lr_vars, sr_spec):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        old = pipeline(original, df_raw.copy(), list(lr_vars), list(sr_spec))
        cand = pipeline(new, df_raw.copy(), list(lr_vars), list(sr_spec))
    assert old.keys() == cand.keys()
    for key in old:
        assert parity.first_difference(old[key], cand[key]) is None, (name, key)


def edge_cases(s):
    return [
        ("backtest-ข้อมูลพอดี-min_train", "_run_backtest", (s.iloc[:8],), {"min_train": 8}),
        ("backtest-ทดสอบ-1-ปี", "_run_backtest", (s.iloc[:9],), {"min_train": 8}),
        ("rolling-ข้อมูลไม่พอ", "_run_rolling_backtest", (s.iloc[:8],), {"min_train": 8, "step_ahead": 1}),
        ("rolling-step-3", "_run_rolling_backtest", (s.iloc[:14],),
         {"min_train": 8, "step_ahead": 3, "crisis_years": (2020, 2022)}),
        ("drift-1-จุด", "_drift_forecast", (s.iloc[:1], 3), {}),
        ("drift-interval-2-จุด", "_drift_forecast_interval", (s.iloc[:2], 5), {}),
        ("drift-interval-3-จุด", "_drift_forecast_interval", (s.iloc[:3], 3), {}),
        ("arima-คงที่", "_auto_arima_forecast", (pd.Series([5.0] * 10, index=range(2000, 2010)), 3), {}),
        ("arima-5-จุด", "_auto_arima_forecast", (s.iloc[:5], 2), {}),
        ("dm-สั้น", "_diebold_mariano", ([1.0], [1.1], [0.9]), {}),
        ("dm-ความแปรปรวน-0", "_diebold_mariano", ([1.0, 2.0, 3.0], [1.5, 2.5, 3.5], [1.5, 2.5, 3.5]), {}),
        ("dm-verdict-ว่าง", "_dm_verdict", (None, "ARIMA", "Naive"), {}),
        ("label-ไม่รู้จัก", "var_label_with_abbr", ("D(ln_UNKNOWN(-2))",), {}),
        ("ชื่อเต็ม-ไม่รู้จัก", "_var_full_name", ("XYZ",), {}),
        ("parse-ไม่ตรงรูปแบบ", "_parse_variable_code", ("ไม่ใช่รหัส",), {}),
        ("stars-None", "_significance_stars", (None,), {}),
        ("stars-nan", "_significance_stars", (float("nan"),), {}),
    ]


def test_forecast_backtest_edge_cases(original, new, computed):
    for name, fn, args, kwargs in edge_cases(computed["outputs"]["tfp_series"]):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            old = outcome(original["F"][fn], *args, **kwargs)
            cand = outcome(new["F"][fn], *args, **kwargs)
        assert parity.first_difference(old, cand) is None, (name, old[:1], cand[:1])


def test_influence_failure_paths(original, new, computed):
    out = computed["outputs"]
    model_df, lr_raw = out["model_df"], out["lr_raw_map"]
    dep_ln = "ln_" + tfp.DEP_VAR
    flat = model_df.copy()
    flat["FDI_GDP"] = 1.0  # ส่วนเบี่ยงเบนมาตรฐาน 0
    flat2 = flat.copy()
    flat2["FEE_GDP"] = 1.0
    cases = [
        ("ตัวแปรเดียว", model_df, ["FDI_GDP"]),
        ("ข้อมูล-2-ปี", model_df.iloc[-2:], list(tfp.LONG_RUN_VARS)),
        ("ไม่มีข้อมูล", model_df.iloc[:0], list(tfp.LONG_RUN_VARS)),
        ("std-0-บางตัว", flat, ["FDI_GDP", "FEE_GDP"]),
        ("std-0-ทุกตัว", flat2, ["FDI_GDP", "FEE_GDP"]),
    ]
    for name, df, lr_vars in cases:
        old = outcome(original["F"]["_compute_influence_df"], df, dep_ln, lr_vars, lr_raw)
        cand = outcome(new["F"]["_compute_influence_df"], df, dep_ln, lr_vars, lr_raw)
        assert parity.first_difference(old, cand) is None, (name, old, cand)


class RecordingClient(replay._FakeClient):
    def __init__(self, tabs, fail_first=0):
        super().__init__(tabs)
        self.keys, self.fail_first = [], fail_first

    def open_by_key(self, key):
        self.keys.append(key)
        if self.fail_first:
            self.fail_first -= 1
            raise gspread.exceptions.APIError(FakeResponse(503))
        return super().open_by_key(key)


class FakeResponse:
    def __init__(self, code):
        self.code, self.text = code, ""

    def json(self):
        return {"error": {"code": self.code, "message": "test", "status": "UNAVAILABLE"}}


class FakeTime:
    def __init__(self):
        self.sleeps = []

    def sleep(self, s):
        self.sleeps.append(s)


def loader_cases():
    tabs = replay.load_tabs()
    data3 = dict(tabs, Data=tabs["Data"][:3])
    no_th = dict(tabs, Researcher=[r for r in tabs["Researcher"] if not (r and "Thailand" in r[0])])
    blank = dict(tabs, Data=tabs["Data"] + [[""] * len(tabs["Data"][0])])
    return [
        ("ค่าเริ่มต้น", tabs, {}, 0),
        ("rdh-จาก-data", tabs, {"rdh_source": "data"}, 0),
        ("rdh-ผิด", tabs, {"rdh_source": "bad"}, 0),
        ("url-เต็ม", tabs, {"url": "https://docs.google.com/spreadsheets/d/AbC-123_x/edit#gid=0"}, 0),
        ("url-id-มีช่องว่าง", tabs, {"url": "  AbC-123_x  "}, 0),
        ("data-3-แถว", data3, {}, 0),
        ("ไม่มีแถว-Thailand", no_th, {}, 0),
        ("แถวว่างท้ายตาราง", blank, {}, 0),
        ("503-แล้วสำเร็จ", tabs, {}, 1),
        ("503-ครบ-3-ครั้ง", tabs, {}, 3),
    ]


@pytest.mark.parametrize("case", loader_cases(), ids=[c[0] for c in loader_cases()])
def test_loader_paths(original, new, monkeypatch, case):
    name, tabs, kwargs, fail_first = case
    results = []
    for side in (original, new):
        client, clock = RecordingClient(tabs, fail_first), FakeTime()
        if side is original:
            side["L"]["_get_client"] = lambda: client
            side["L"]["time"] = clock
        else:
            monkeypatch.setattr(data_loader, "_get_client", lambda: client)
            monkeypatch.setattr(data_loader, "time", clock)
        results.append([outcome(side["L"]["load_data_gsheet"], **kwargs), client.keys, clock.sleeps])
    assert parity.first_difference(fingerprint.canonical(results[0]), fingerprint.canonical(results[1])) is None
