"""ชื่อที่โค้ดหน้าเดิม (page_script.py) เรียก แต่ในระบบใหม่ต้องทำงานต่างจากเดิม

หน้าเว็บไม่ fit โมเดลและไม่เรียกบริการภายนอกเอง:
- ฟังก์ชันที่ fit โมเดล (run_long_run, run_short_run, run_diagnostics, _run_backtest, _run_rolling_backtest และ
  ฟังก์ชันที่ต้องใช้ผล statsmodels) อ่านผลที่ worker คำนวณไว้ (compute.py) — ตรวจว่า argument ตรงกับที่คำนวณ
  ถ้ายังไม่มีผลจะสร้าง job แล้วหยุดรอ (ui.Pending) ไม่คำนวณแทนในหน้า
- ดึงชีต / Gemini / รายงาน เป็น job ของ worker เมื่อเสร็จจะรันหน้าใหม่โดยกดปุ่มเดิมซ้ำให้ (เหมือนรอบที่ผู้ใช้กด)
- ฟังก์ชันที่ไม่ fit โมเดล (build_model_frame, ตัวสร้างกราฟ ฯลฯ) ใช้ของจริงที่ย้ายมา
ค่าของหนึ่งคำขออยู่ใน PageContext (contextvar) ที่ page_runner.py ตั้งให้
"""
from __future__ import annotations

import base64
import contextvars
import functools
import inspect

from . import charts, compute
from .modeling import core, tfp
from .ui import Pending

CURRENT: contextvars.ContextVar = contextvars.ContextVar("tfp_page_context")

# ----- ค่าคงที่และฟังก์ชันที่ไม่ fit โมเดล (ของจริงที่ย้ายมา) -----
LONG_RUN_VARS = tfp.LONG_RUN_VARS
SHORT_RUN_SPEC = tfp.SHORT_RUN_SPEC
DEP_VAR = tfp.DEP_VAR
ADF_DIFF_TREND = tfp.ADF_DIFF_TREND    # แอป 7bf84e4 import จาก TFP (TFP_App1.3.0.py:81-86)
ADF_LEVEL_TREND = tfp.ADF_LEVEL_TREND
build_tfpi_yoy_summary = tfp.build_tfpi_yoy_summary
CANDIDATE_VARS = tfp.CANDIDATE_VARS
_mape_threshold_chart = charts._mape_threshold_chart


def build_model_frame(df):
    ctx = CURRENT.get()
    out = tfp.build_model_frame(df)
    dataset_id = ctx.dataset_of(df)
    if dataset_id is not None:
        ctx.model_frames[id(out)] = dataset_id
        ctx.keep.append(out)
    return out


# ----- ตัวสร้างกราฟ: ของเดิมวางกราฟ (และคำอธิบาย) ลงหน้าเอง -----
def _nice_line_chart(*args, **kwargs):
    CURRENT.get().st.altair_chart(charts._nice_line_chart(*args, **kwargs), use_container_width=True)


def _nice_line_chart_with_forecast(*args, **kwargs):
    st = CURRENT.get().st
    chart, legend_html = charts._nice_line_chart_with_forecast(*args, **kwargs)
    st.altair_chart(chart, use_container_width=True)
    st.markdown(legend_html, unsafe_allow_html=True)


# ----- ผลโมเดลที่ worker คำนวณไว้ -----
class FitResult:
    """แทนผล statsmodels ในหน้าเว็บ ใช้ได้กับฟังก์ชันอ่านผลด้านล่างเท่านั้น"""

    def __init__(self, bundle: dict, part: str):
        self.bundle, self.part = bundle, part

    @property
    def params(self):
        """ค่าสัมประสิทธิ์ของโมเดล (pandas Series เดิมของ statsmodels) — 4c8aa71 หน้าอ่าน sr_res.params (แอป :4423)"""
        part = self.bundle.get(self.part) or {}
        _require("params" in part, f"params ของผล {self.part} ไม่ได้คำนวณไว้")
        return part["params"].copy()


class ArgumentMismatch(RuntimeError):
    """หน้าเรียกด้วย argument ที่ไม่ได้คำนวณไว้ — ไม่คำนวณแทน (ต้องแก้โค้ด ไม่ใช่ข้อมูล)"""


def _require(cond, what):
    if not cond:
        raise ArgumentMismatch(what)


def run_long_run(df, dep, long_run_vars):
    ctx = CURRENT.get()
    _require(id(df) in ctx.model_frames, "model_df ไม่ได้มาจากข้อมูลของ session")
    _require(dep == "ln_" + tfp.DEP_VAR, "ตัวแปรตาม")
    b = ctx.ecm_bundle(ctx.model_frames[id(df)], list(long_run_vars))
    if "error" in b:
        raise compute.replay_error(b["error"])
    resid = b["lr"]["resid"].copy()
    ctx.keep.append(resid)
    ctx.resids[id(resid)] = b
    return FitResult(b, "lr"), resid


def run_short_run(df, dep, short_run_spec, lr_resid, *args, **kwargs):
    ctx = CURRENT.get()
    _require(not args and not kwargs, "argument เพิ่มเติมของ run_short_run")
    b = ctx.resids.get(id(lr_resid))
    _require(b is not None and id(df) in ctx.model_frames, "ผลระยะยาวไม่ตรงกับที่คำนวณไว้")
    _require(list(short_run_spec) == list(b["sr_spec"]), "ชุดตัวแปรระยะสั้น")
    return None if b["sr"] is None else FitResult(b, "sr")


def build_coefficient_tables(lr_res, sr_res):
    _require(isinstance(lr_res, FitResult) and isinstance(sr_res, FitResult) and lr_res.bundle is sr_res.bundle,
             "ผลโมเดลสำหรับตารางค่าสัมประสิทธิ์")
    lr_table, sr_table = lr_res.bundle["tables"]
    return lr_table.copy(), sr_table.copy()


def summary_adj_r2(res):
    _require(isinstance(res, FitResult), "ผลโมเดลสำหรับ Adj. R²")
    return res.bundle[res.part]["adj_r2"]


def _unrounded_coefficient_table(res):
    _require(isinstance(res, FitResult), "ผลโมเดลสำหรับตารางค่าไม่ปัด")
    return res.bundle[res.part]["unrounded"].copy()


def run_diagnostics(model_df, dep_ln, long_run_vars, lr_res, sr_res, lr_resid, short_run_spec=None):
    ctx = CURRENT.get()
    _require(isinstance(lr_res, FitResult) and isinstance(sr_res, FitResult) and lr_res.bundle is sr_res.bundle,
             "ผลโมเดลสำหรับ diagnostics")
    b = lr_res.bundle
    _require(id(model_df) in ctx.model_frames and dep_ln == "ln_" + tfp.DEP_VAR
             and list(long_run_vars) == b["lr_vars"] and ctx.resids.get(id(lr_resid)) is b
             and short_run_spec is not None and list(short_run_spec) == list(b["sr_spec"]), "argument ของ diagnostics")
    d = b["diag"]
    if "error" in d:
        raise compute.replay_error(d["error"])
    return d["table"].copy()


def _build_adf_detail_table(model_df, dep_ln, lr_vars, sr_spec):
    """ตาราง ADF รายตัวแปร (7bf84e4 TFP_App1.3.0.py:3310-3336) — worker คำนวณไว้ใน ECM bundle ต่อจาก diagnostics
    หน้าไม่เรียก adf_report เอง; ข้อผิดพลาดตอนคำนวณส่งกลับเป็น exception ชนิด/ข้อความเดิมให้ except ของหน้า (:3389-3391)"""
    ctx = CURRENT.get()
    _require(id(model_df) in ctx.model_frames and dep_ln == "ln_" + tfp.DEP_VAR, "argument ของตาราง ADF")
    b = ctx.ecm_bundle(ctx.model_frames[id(model_df)], list(lr_vars))
    _require(list(sr_spec) == list(b["sr_spec"]) and "adf_detail" in b, "ชุดตัวแปรของตาราง ADF")
    a = b["adf_detail"]
    if "error" in a:
        raise compute.replay_error(a["error"])
    return a["table"].copy()


def adf_report(series, name):
    """Read the worker's original ADF result for a newly selected variable (acc64ee)."""
    ctx = CURRENT.get()
    for frame in ctx.keep:
        if id(frame) in ctx.model_frames and name in frame.columns and frame[name].equals(series):
            b = ctx.ecm_bundle(ctx.model_frames[id(frame)], list(ctx.st.values["active_long_run_vars"]))
            rec = b["adf_candidates"][name]
            if "error" in rec:
                raise compute.replay_error(rec["error"])
            return dict(rec["result"])
    raise ArgumentMismatch("ADF series does not match the session model frame")


def _same_call(fn, args, kwargs, expected_kwargs) -> bool:
    bound = inspect.signature(fn).bind(*args, **kwargs)
    bound.apply_defaults()
    want = inspect.signature(fn).bind(None, **expected_kwargs)
    want.apply_defaults()
    got = dict(bound.arguments)
    exp = dict(want.arguments)
    got.pop("tfp_series")
    exp.pop("tfp_series")
    return got == exp


def _run_backtest(*args, **kwargs):
    ctx = CURRENT.get()
    _require(_same_call(core._run_backtest, args, kwargs, compute.HOLDOUT_KWARGS), "argument ของ holdout backtest")
    b = ctx.series_bundle(args[0] if args else kwargs["tfp_series"])
    return _copy(b["holdout"])


def _run_rolling_backtest(*args, **kwargs):
    ctx = CURRENT.get()
    _require(_same_call(core._run_rolling_backtest, args, kwargs, compute.ROLLING_KWARGS),
             "argument ของ rolling backtest")
    b = ctx.series_bundle(args[0] if args else kwargs["tfp_series"])
    return _copy(b["rolling"])


_BT_KINDS = {"holdout": (core._run_backtest, compute.HOLDOUT_KWARGS),
             "rolling": (core._run_rolling_backtest, compute.ROLLING_KWARGS)}


def _bt_cache_has(kind, series, **params):
    """แทน TFP_App1.3.0.py:4022 (4c8aa71) — เดิม: มีผลในไฟล์ backtest_cache.pkl หรือยัง
    ระบบใหม่ไม่ใช้ไฟล์ (ผู้ใช้เลือก 20 ต.ค.): มีผล backtest ของข้อมูลชุดนี้ที่ worker คำนวณไว้ใน DB หรือยัง ไม่สร้าง job"""
    fn, expected = _BT_KINDS[kind]
    _require(_same_call(fn, (series,), params, expected), f"argument ของ {kind} backtest")
    return CURRENT.get().has_series_bundle(series)


def _backtest_with_file_cache(kind, func, series, **params):
    """แทน TFP_App1.3.0.py:4007 (4c8aa71) — เดิม: อ่านผลจากไฟล์ ไม่มีก็คำนวณแล้วบันทึกลงไฟล์ คืน (ผล, มาจากไฟล์หรือไม่)
    ระบบใหม่: func คือ _run_backtest/_run_rolling_backtest ด้านบน (อ่านผลของ worker ถ้ายังไม่มีจะสร้าง job แล้วหน้ารอ)
    ผลเก็บใน DB ต่อชุดข้อมูล ใช้ร่วมกันทุก session แบบเดียวกับไฟล์เดิม; ค่าที่สองหน้าเดิมไม่ได้ใช้"""
    had = _bt_cache_has(kind, series, **params)
    return func(series, **params), had


def _copy(obj):
    if hasattr(obj, "copy") and not isinstance(obj, (dict, list)):
        return obj.copy()
    if isinstance(obj, tuple):
        return tuple(_copy(x) for x in obj)
    if isinstance(obj, list):
        return [_copy(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _copy(v) for k, v in obj.items()}
    return obj


# ----- งานที่มีผลภายนอก: เป็น job ของ worker -----
def _load_data_gsheet_with_optional_url(url=None):
    return CURRENT.get().fetch(url)


def _page_clock(now):
    """เวลาที่ now_th() ของหน้าเดิมเห็น — หน้าเดิมทำงานต่อทันทีหลังอ่านชีตเสร็จ เวลา "ดึงข้อมูลล่าสุดเมื่อ" และประวัติการดึง
    จึงเป็นเวลาอ่านชีตสำเร็จ (TFP_App1.3.0.py:3228-3229, 6660-6661) แต่ระบบใหม่รันหน้าต่อหลังงานดึงชีตและคำนวณค่าเริ่มต้นเสร็จ
    ส่วนที่เหลือของคำขอนั้นจึงนับเวลาต่อจากเวลาที่ worker อ่านชีตสำเร็จ (แผน §9A) คำขออื่นใช้เวลาจริง"""
    ctx = CURRENT.get(None)
    return now if ctx is None or ctx.clock_shift is None else now + ctx.clock_shift


def generate_summary_gemini(lr_res, sr_res, model_df, dep_ln):
    """ฟังก์ชันเดิม (summary.py) รันใน job ของ worker ด้วยผล fit จริงของชุดตัวแปรเดียวกับที่หน้าแสดง"""
    ctx = CURRENT.get()
    _require(isinstance(lr_res, FitResult) and isinstance(sr_res, FitResult) and lr_res.bundle is sr_res.bundle
             and id(model_df) in ctx.model_frames and dep_ln == "ln_" + tfp.DEP_VAR, "argument ของการสรุปด้วย Gemini")
    b = lr_res.bundle
    return ctx.summary(ctx.model_frames[id(model_df)], b["lr_vars"], b["sr_spec"])


def build_word_report(*args, **kwargs):
    return CURRENT.get().report("word", args, kwargs)


def build_pptx_report(*args, **kwargs):
    return CURRENT.get().report("pptx", args, kwargs)


# ----- บันทึกการดึงข้อมูล (เดิมเป็นไฟล์ fetch_log.csv ข้างแอป ตอนนี้อยู่ใน Postgres) -----
def _fetch_log_append(row: dict) -> None:
    CURRENT.get().store.fetch_log_append(row)


def _fetch_log_rows() -> list:
    return CURRENT.get().store.fetch_log_rows()


# ----- ไฟล์ภาพ/ฟอนต์ในหน้า (ไฟล์ใน image ไม่เปลี่ยน อ่านครั้งเดียวต่อ process) -----
@functools.lru_cache(maxsize=None)
def _cached_file_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()
