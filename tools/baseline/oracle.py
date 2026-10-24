"""Step 1: เรียกฟังก์ชันคำนวณของระบบเดิมบน snapshot แล้วเก็บผลเป็น oracle (ตัวเทียบ)

ฐานงาน: repo เพื่อน main @ e6aee03 (ไฟล์แอป TFP_App1.3.0.py)
- ข้อมูลเข้า: snapshot ใน private/baseline/sheets_raw.json ผ่าน loader เดิม (replay.py)
- ฟังก์ชันใน TFP.py: import ตรง ๆ
- ฟังก์ชันในไฟล์แอป: ดึง source ของฟังก์ชันและค่าคงที่ที่ต้องใช้ด้วย AST แล้ว exec ตามเดิม
  ถอดเฉพาะ decorator st.cache_data (มีผลแค่การ cache ไม่มีผลกับตัวเลข)
  ไม่ import ไฟล์แอปทั้งไฟล์ เพราะจะรันโค้ดหน้าเว็บของ Streamlit
- ลำดับการเรียกและค่าเริ่มต้นเลียนแบบ TFP_App1.3.0.py บรรทัด 3309–3341 (ECM และค่าสัมประสิทธิ์
  แบบไม่ปัด), 4559 (พยากรณ์หลัก Random walk with drift), 4699 (rolling), 4883 (holdout),
  5990 (influence)
- ARIMA ถูกเรียกเฉพาะใน backtest ห่อให้จดคำเตือนและสถานะ converge ของทุก fit
  (ไม่เปลี่ยนตัวเลข ตรวจซ้ำใน instrumentation_neutral)

ผลเต็มเก็บใน private/baseline/oracle_<ชื่อ>.json (มีค่าข้อมูล ไม่ขึ้น git)

ต้องตั้ง PYTHONHASHSEED=0 เสมอ: ตาราง diagnostics ตัดสินเสมอด้วยลำดับของ set
(TFP.py:427) ซึ่งเปลี่ยนตาม hash seed ของแต่ละ process ถ้าไม่ตรึง seed ผลอาจไม่คงที่

ชื่อผลต้องไม่ซ้ำกับที่มีอยู่ (ตรวจก่อนเริ่มคำนวณ และเขียนแบบห้ามทับ) ถ้าไม่ระบุชื่อจะใช้เวลาปัจจุบัน

    PYTHONHASHSEED=0 /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/oracle.py [ชื่อใหม่]
"""
import ast
import contextlib
import datetime
import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import re
import sys
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "private" / "baseline"
sys.path.insert(0, str(HERE))
import safe_io  # noqa: E402

PACKAGES = ["numpy", "pandas", "scipy", "statsmodels", "patsy"]


def output_path(name: str) -> Path:
    return OUT / f"oracle_{safe_io.check_name(name)}.json"


def ensure_new(name: str) -> Path:
    path = output_path(name)
    safe_io.ensure_absent([path])
    return path

APP_FILE = "TFP_App1.3.0.py"
APP_TARGETS = [
    "_auto_arima_forecast", "_drift_forecast_interval", "_run_backtest", "_run_rolling_backtest",
    "_compute_influence_df", "_extract_raw_coefficients", "_unrounded_coefficient_table",
    "_merge_coefficient_tables", "var_label_with_abbr",
    "_build_adf_detail_table",  # มีตั้งแต่ 7bf84e4 (ต้นฉบับรุ่นก่อนไม่มี — extract_app_functions ข้ามชื่อที่ไม่มีในไฟล์)
]
STRIPPABLE_DECORATOR_PREFIX = "st.cache_data"
HORIZONS = [3, 5, 10, 15]      # TFP_App1.3.0.py:4549
MIN_POINTS_FOR_ARIMA = 8       # TFP_App1.3.0.py:4480
CRISIS_YEARS = (2020, 2022)    # TFP_App1.3.0.py:4701
TFP_NAMES_IMPORTED_BY_APP = [  # TFP_App1.3.0.py:81-86 (ADF_DIFF_TREND/ADF_LEVEL_TREND app import ตั้งแต่ 7bf84e4)
    "build_model_frame", "run_long_run", "run_short_run", "build_coefficient_tables",
    "build_tfpi_yoy_summary", "summary_adj_r2", "adf_report", "run_diagnostics",
    "LONG_RUN_VARS", "SHORT_RUN_SPEC", "DEP_VAR", "ADF_DIFF_TREND", "ADF_LEVEL_TREND", "CANDIDATE_VARS",
]

FIT_LOG = []


def make_recording_arima(base):
    class RecordingARIMA(base):
        def __init__(self, endog, *args, **kwargs):
            super().__init__(endog, *args, **kwargs)
            self._rec = {"order": list(kwargs.get("order", ())), "trend": kwargs.get("trend"),
                         "nobs": int(len(endog))}

        def fit(self, *args, **kwargs):
            entry = dict(self._rec)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    res = super().fit(*args, **kwargs)
                except Exception as e:
                    entry["error"] = type(e).__name__
                    FIT_LOG.append(entry)
                    raise
            entry["converged"] = (res.mle_retvals or {}).get("converged")
            entry["warnings"] = sorted({f"{w.category.__name__}: {str(w.message)[:90]}" for w in caught})
            FIT_LOG.append(entry)
            return res

    return RecordingARIMA


def extract_app_functions(namespace: dict) -> dict:
    """exec ฟังก์ชันเป้าหมายจากไฟล์แอปพร้อมฟังก์ชัน/ค่าคงที่ระดับไฟล์ที่มันอ้างถึง
    คืน sha256 ของ source แต่ละชิ้นที่ใช้ เพื่อใช้ยืนยันว่าเป็นโค้ดเดิม"""
    src = (REPO / APP_FILE).read_text(encoding="utf-8")
    tree = ast.parse(src)
    defs, assigns = {}, {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if node.name in defs:
                raise RuntimeError(f"ฟังก์ชัน {node.name} ถูกนิยามซ้ำใน {APP_FILE}")
            defs[node.name] = node
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigns.setdefault(node.targets[0].id, []).append(node)

    chosen, seen, queue = [], set(), list(APP_TARGETS)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in defs:
            node = defs[name]
        elif name in assigns:
            if len(assigns[name]) > 1:
                raise RuntimeError(f"{name} ถูกกำหนดค่าหลายครั้งใน {APP_FILE} เลือกเองไม่ได้")
            node = assigns[name][0]
        else:
            continue
        chosen.append(node)
        local_names = set()
        if isinstance(node, ast.FunctionDef):
            a = node.args
            local_names = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
            local_names |= {x.arg for x in (a.vararg, a.kwarg) if x}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    local_names.add(sub.id)
                elif isinstance(sub, (ast.FunctionDef, ast.Lambda)) and sub is not node:
                    if isinstance(sub, ast.FunctionDef):
                        local_names.add(sub.name)
                    local_names |= {x.arg for x in sub.args.args}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id not in namespace:
                if sub.id not in local_names and (sub.id in defs or sub.id in assigns):
                    queue.append(sub.id)

    source_hashes = {}
    for node in chosen:
        name = node.name if isinstance(node, ast.FunctionDef) else node.targets[0].id
        source_hashes[name] = hashlib.sha256(ast.get_source_segment(src, node).encode("utf-8")).hexdigest()
        if isinstance(node, ast.FunctionDef):
            kept = []
            for dec in node.decorator_list:
                text = ast.unparse(dec)
                if not text.startswith(STRIPPABLE_DECORATOR_PREFIX):
                    raise RuntimeError(f"{node.name} มี decorator ที่ไม่รู้จัก: {text}")
            node.decorator_list = kept
    chosen.sort(key=lambda n: n.lineno)
    exec(compile(ast.Module(body=chosen, type_ignores=[]), str(REPO / APP_FILE), "exec"), namespace)
    return source_hashes


def run(run_name: str) -> dict:
    sys.path[:0] = [str(REPO), str(HERE)]
    import numpy as np
    import pandas as pd
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    import fingerprint
    import replay
    import runtime_info
    import TFP
    from typing import Optional

    # สถานะ warnings แบบเดียวกับ app.py:56-57 (มีผลแค่การแสดงคำเตือน)
    warnings.simplefilter("ignore", ConvergenceWarning)
    warnings.simplefilter("ignore", UserWarning)

    base_ns = {"np": np, "pd": pd, "re": re, "math": math, "warnings": warnings,
               "adfuller": adfuller, "ConvergenceWarning": ConvergenceWarning,
               "Optional": Optional}  # 4c8aa71: annotation ของ _run_rolling_backtest (แอป :89 from typing import Optional)
    base_ns.update({n: getattr(TFP, n) for n in TFP_NAMES_IMPORTED_BY_APP})
    ns = dict(base_ns, ARIMA=make_recording_arima(ARIMA))
    source_hashes = extract_app_functions(ns)

    timings = {}

    def timed(label, fn, *args, **kwargs):
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            value = fn(*args, **kwargs)
        timings[label] = round(time.perf_counter() - t0, 4)
        return value

    df_raw = timed("load_snapshot", replay.load_df_from_snapshot)

    # ECM — TFP_App1.3.0.py:3309-3341 (ค่าเริ่มต้นของชุดตัวแปรมาจาก LONG_RUN_VARS/SHORT_RUN_SPEC)
    active_lr_vars = list(TFP.LONG_RUN_VARS)
    active_sr_spec = list(TFP.SHORT_RUN_SPEC)
    model_df = timed("build_model_frame", TFP.build_model_frame, df_raw)
    dep_ln = "ln_" + TFP.DEP_VAR
    lr_res, lr_resid = timed("run_long_run", TFP.run_long_run, model_df, dep_ln, active_lr_vars)
    sr_res = timed("run_short_run", TFP.run_short_run, model_df, dep_ln, active_sr_spec, lr_resid)
    if sr_res is None:
        raise RuntimeError("run_short_run คืน None (พารามิเตอร์ >= observations)")
    lr_table, sr_table = TFP.build_coefficient_tables(lr_res, sr_res)
    combined_table = ns["_merge_coefficient_tables"](lr_table, sr_table)
    # ค่าดิบที่ยังไม่ปัด (TFP_App1.3.0.py:3328-3329) ใช้ต่อกับ influence/scenario
    lr_raw_map = ns["_extract_raw_coefficients"](ns["_unrounded_coefficient_table"](lr_res))
    sr_raw_map = ns["_extract_raw_coefficients"](ns["_unrounded_coefficient_table"](sr_res))
    adj_r2 = [TFP.summary_adj_r2(lr_res), TFP.summary_adj_r2(sr_res)]
    diag_table = timed("run_diagnostics", TFP.run_diagnostics, model_df, dep_ln, active_lr_vars,
                       lr_res, sr_res, lr_resid, short_run_spec=active_sr_spec)
    diag_display = diag_table.copy()
    diag_display["รายการ"] = diag_display["รายการ"].apply(ns["var_label_with_abbr"])
    n_fail = int((diag_table["สถานะ"] == "🔴 ไม่ผ่าน").sum())
    n_watch = int(diag_table["สถานะ"].str.startswith("🟡").sum())
    n_pass = int(len(diag_table) - n_fail - n_watch)
    # ตาราง ADF รายตัวแปร — 7bf84e4 TFP_App1.3.0.py:3384-3391 (ต่อจาก diagnostics) ต้นฉบับรุ่นก่อนไม่มี จึงไม่มีค่านี้ในผล
    extra = {}
    if "_build_adf_detail_table" in ns:
        extra["adf_detail"] = timed("adf_detail", ns["_build_adf_detail_table"], model_df, dep_ln,
                                    active_lr_vars, active_sr_spec)

    # พยากรณ์หลัก — TFP_App1.3.0.py:4559, 5813 (Random walk with drift เรียกแยกทีละ horizon)
    tfp_series = model_df[TFP.DEP_VAR].dropna().sort_index()
    forecasts, fit_groups = {}, {}
    for h in HORIZONS:
        forecasts[h] = timed(f"drift_h{h}", ns["_drift_forecast_interval"], tfp_series, h)
    slice_identical = {
        h: fingerprint.dumps(forecasts[h]) == fingerprint.dumps(forecasts[15].iloc[:h])
        for h in HORIZONS
    }

    # ตรวจว่าตัวห่อ ARIMA (ใช้ใน backtest) ไม่เปลี่ยนตัวเลข: รัน h=15 ทั้งสองแบบแล้วเทียบ
    start = len(FIT_LOG)
    wrapped_h15 = ns["_auto_arima_forecast"](tfp_series, 15)
    fit_groups["neutrality_check_h15"] = FIT_LOG[start:]
    plain_ns = dict(base_ns, ARIMA=ARIMA)
    extract_app_functions(plain_ns)
    plain_h15 = plain_ns["_auto_arima_forecast"](tfp_series, 15)
    instrumentation_neutral = fingerprint.dumps(plain_h15) == fingerprint.dumps(wrapped_h15)

    # backtests — TFP_App1.3.0.py:4883 (holdout), 4699 (rolling)
    start = len(FIT_LOG)
    holdout = timed("holdout_backtest", ns["_run_backtest"], tfp_series, min_train=MIN_POINTS_FOR_ARIMA)
    fit_groups["holdout"] = FIT_LOG[start:]
    start = len(FIT_LOG)
    rolling = timed("rolling_backtest", ns["_run_rolling_backtest"], tfp_series,
                    min_train=MIN_POINTS_FOR_ARIMA, step_ahead=1, crisis_years=CRISIS_YEARS)
    fit_groups["rolling"] = FIT_LOG[start:]

    # influence — TFP_App1.3.0.py:5990
    influence = ns["_compute_influence_df"](model_df, dep_ln, active_lr_vars, lr_raw_map)

    def sample_index(res):
        return [int(i) for i in res.model.data.row_labels]

    outputs = {
        "raw_df": df_raw, "model_df": model_df,
        "lr.params": lr_res.params, "lr.bse": lr_res.bse, "lr.tvalues": lr_res.tvalues,
        "lr.pvalues": lr_res.pvalues, "lr.rsquared": lr_res.rsquared, "lr.nobs": lr_res.nobs,
        "lr.sample_index": sample_index(lr_res), "lr.resid": lr_resid,
        "lr.eg": [lr_res.eg_stat, lr_res.eg_pvalue, list(lr_res.eg_crit)],
        "sr.params": sr_res.params, "sr.bse": sr_res.bse, "sr.tvalues": sr_res.tvalues,
        "sr.pvalues": sr_res.pvalues, "sr.rsquared": sr_res.rsquared, "sr.nobs": sr_res.nobs,
        "sr.sample_index": sample_index(sr_res),
        "adj_r2": adj_r2, "lr_table": lr_table, "sr_table": sr_table, "combined_table": combined_table,
        "lr_raw_map": lr_raw_map, "sr_raw_map": sr_raw_map,
        "diag_table": diag_table, "diag_display": diag_display, "diag_counts": [n_fail, n_watch, n_pass],
        "tfp_series": tfp_series,
        **{f"forecast.h{h}": forecasts[h] for h in HORIZONS},
        "holdout": holdout, "rolling": rolling, "influence": influence, **extra,
    }
    result = {
        "run": run_name,
        "hash_seed": os.environ.get("PYTHONHASHSEED"),
        "python": platform.python_version(),
        "packages": {p: importlib.metadata.version(p) for p in PACKAGES},
        "runtime": runtime_info.runtime_identity(),
        "snapshot_sha256": fingerprint.sha256(replay.load_tabs()),
        "source_hashes": source_hashes,
        "file_hashes": {f: hashlib.sha256((REPO / f).read_bytes()).hexdigest()
                        for f in [APP_FILE, "TFP.py", "data_loader.py"]},
        "output_hashes": {k: fingerprint.sha256(v) for k, v in outputs.items()},
        "slice_identical": slice_identical,
        "instrumentation_neutral": instrumentation_neutral,
        "fit_groups": fit_groups,
        "timings_s": timings,
    }
    safe_io.write_new(
        output_path(run_name),
        json.dumps(dict(result, outputs={k: fingerprint.canonical(v) for k, v in outputs.items()}),
                   ensure_ascii=False))
    result["headline"] = {
        "adj_r2": [round(x, 4) for x in adj_r2],
        "nobs": [int(lr_res.nobs), int(sr_res.nobs)],
        "lr_sample": [min(sample_index(lr_res)), max(sample_index(lr_res))],
        "sr_sample": [min(sample_index(sr_res)), max(sample_index(sr_res))],
        "ecm_lag1": [round(float(sr_res.params["ECM_lag1"]), 4), round(float(sr_res.pvalues["ECM_lag1"]), 4)],
        "eg_pvalue": round(float(lr_res.eg_pvalue), 4),
        "diag_counts_fail_watch_pass": [n_fail, n_watch, n_pass],
        "tfp_series_years": [int(tfp_series.index.min()), int(tfp_series.index.max()), len(tfp_series)],
        "drift_last": {h: round(float(forecasts[h]["mean"].iloc[-1]), 4) for h in HORIZONS},
        "holdout_mape_arima_naive_drift": [round(holdout[1][f"{m}_mape"], 4) for m in ("arima", "naive", "drift")],
        "rolling_mape_arima_naive_drift": [round(rolling[1][f"{m}_mape"], 4) for m in ("arima", "naive", "drift")],
        "rolling_best_model": rolling[1].get("best_model"),
        "rolling_windows": rolling[1]["n_windows"],
        "influence_rows": 0 if influence[0] is None else len(influence[0]),
    }
    return result


if __name__ == "__main__":
    if os.environ.get("PYTHONHASHSEED") != "0":
        sys.exit("ต้องรันด้วย PYTHONHASHSEED=0 (ดูเหตุผลในหัวไฟล์)")
    name = sys.argv[1] if len(sys.argv) > 1 else "run-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        ensure_new(name)  # ตรวจก่อนคำนวณ
    except (FileExistsError, ValueError) as e:
        sys.exit(str(e))
    res = run(name)
    summary = {k: res[k] for k in ["run", "headline", "slice_identical", "instrumentation_neutral", "timings_s"]}
    summary["fit_counts"] = {g: {"fits": len(f), "not_converged": sum(1 for x in f if x.get("converged") is False),
                                 "with_warnings": sum(1 for x in f if x.get("warnings"))}
                             for g, f in res["fit_groups"].items()}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
