"""ผลคำนวณที่ worker เตรียมไว้ให้หน้าเว็บอ่าน (หน้าเว็บไม่ fit โมเดลเอง)

เรียกฟังก์ชันที่ย้ายมาในลำดับและด้วย argument เดียวกับโค้ดหน้าเดิม:
- ECM ต่อชุดตัวแปร — TFP_App1.3.0.py:3313-3346 (run_long_run → run_short_run → ตาราง/ค่าไม่ปัด/Adj. R² → diagnostics)
  + ตาราง ADF รายตัวแปรต่อจาก diagnostics (7bf84e4 :3384-3391) — เลขบรรทัดอื่นในไฟล์นี้อ้าง e6aee03
- backtest ต่อชุดข้อมูล — :4883 (holdout) และ :4699 (rolling, ช่วงวิกฤต 2020–2022)
ผลเก็บแบบไม่สูญเสียด้วย codec.py และเก็บ exception (ชนิด+ข้อความ) ในจุดที่หน้าเดิมมี try/except
"""
import builtins
import contextlib
import io

from . import codec
from .modeling import core, tfp

MIN_POINTS_FOR_ARIMA = 8        # TFP_App1.3.0.py:4480
CRISIS_YEARS = (2020, 2022)     # TFP_App1.3.0.py:4701
HOLDOUT_KWARGS = {"min_train": MIN_POINTS_FOR_ARIMA}
ROLLING_KWARGS = {"min_train": MIN_POINTS_FOR_ARIMA, "step_ahead": 1, "crisis_years": CRISIS_YEARS}


def error_record(e: BaseException) -> dict:
    return {"type": type(e).__name__, "text": str(e)}


def replay_error(rec: dict) -> Exception:
    """สร้าง exception ที่ชื่อชนิดและข้อความ (str) ตรงกับของเดิม เพื่อให้ except/f-string ในหน้าเดิมได้ผลเดิม"""
    base = getattr(builtins, rec["type"], None)
    if not (isinstance(base, type) and issubclass(base, Exception)):
        base = Exception
    text = rec["text"]
    cls = type(rec["type"], (base,), {"__str__": lambda self: text, "__module__": "builtins"})
    return cls(text)


def _quiet(fn, *args, **kwargs):
    """TFP.py พิมพ์ผล regression ออก stdout — ไม่ให้ไปปน log ของ worker"""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def ecm_bundle(raw_df, lr_vars: list, sr_spec: list) -> dict:
    model_df = tfp.build_model_frame(raw_df)
    dep_ln = "ln_" + tfp.DEP_VAR
    out = {"lr_vars": list(lr_vars), "sr_spec": list(sr_spec)}
    try:  # หน้าเดิมไม่มี try ตรงนี้ ถ้าล้มหน้าจะหยุดด้วย error — เก็บไว้ให้หน้าใหม่ล้มแบบเดียวกัน
        lr_res, lr_resid = _quiet(tfp.run_long_run, model_df, dep_ln, list(lr_vars))
        sr_res = _quiet(tfp.run_short_run, model_df, dep_ln, list(sr_spec), lr_resid)
    except Exception as e:
        out["error"] = error_record(e)
        return out
    out["lr"] = {"resid": lr_resid, "unrounded": core._unrounded_coefficient_table(lr_res),
                 "adj_r2": tfp.summary_adj_r2(lr_res)}
    out["sr"] = None
    if sr_res is not None:
        out["sr"] = {"unrounded": core._unrounded_coefficient_table(sr_res), "adj_r2": tfp.summary_adj_r2(sr_res),
                     "params": sr_res.params}  # 4c8aa71: หน้าแสดง α = params["ECM_lag1"] และ Half-life (แอป :4423)
        out["tables"] = tfp.build_coefficient_tables(lr_res, sr_res)
        try:
            out["diag"] = {"table": _quiet(tfp.run_diagnostics, model_df, dep_ln, list(lr_vars), lr_res, sr_res,
                                           lr_resid, short_run_spec=list(sr_spec))}
        except Exception as e:  # หน้าเดิมจับ Exception แล้วแสดงข้อความ (TFP_App1.3.0.py:3342-3343)
            out["diag"] = {"error": error_record(e)}
        try:  # หน้าเดิมจับ Exception แล้วแสดง st.info (7bf84e4 TFP_App1.3.0.py:3387-3391)
            out["adf_detail"] = {"table": _quiet(core._build_adf_detail_table, model_df, dep_ln, list(lr_vars),
                                                  list(sr_spec))}
        except Exception as e:
            out["adf_detail"] = {"error": error_record(e)}
    # Defaults for new short-run variables must use original ADF without fitting in API requests.
    out["adf_candidates"] = {}
    for name in tfp.CANDIDATE_VARS:
        if name in model_df.columns:
            try:
                out["adf_candidates"][name] = {"result": _quiet(tfp.adf_report, model_df[name], name)}
            except Exception as e:
                out["adf_candidates"][name] = {"error": error_record(e)}
    return out


def series_bundle(raw_df) -> dict:
    model_df = tfp.build_model_frame(raw_df)
    tfp_series = model_df[tfp.DEP_VAR].dropna().sort_index()
    return {
        "tfp_series": tfp_series,
        "holdout": core._run_backtest(tfp_series, **HOLDOUT_KWARGS),
        "rolling": core._run_rolling_backtest(tfp_series, **ROLLING_KWARGS),
    }


def pack(bundle: dict) -> dict:
    return codec.encode(bundle)


def unpack(data: dict) -> dict:
    return codec.decode(data)
