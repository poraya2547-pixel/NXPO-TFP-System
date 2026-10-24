"""งานที่ worker ทำ (หน้าเว็บสร้าง job แล้วรอผล — ดู page_api.py)

- fetch: ดึงชีตด้วย loader เดิม → เก็บ dataset (ไม่ซ้ำตาม hash ของเนื้อหา) → เตรียมผลค่าเริ่มต้นที่หน้าเดิมใช้
  (ECM ชุดตัวแปรเริ่มต้น) ก่อนแจ้งว่าเสร็จ (แผน §9) — ผลบอกเวลาที่อ่านชีตสำเร็จ (read_at, แผน §9A)
- ecm: ECM ของชุดตัวแปรที่คณะวิจัยเลือก · series: backtest ของ dataset (ถ้ายังไม่มี) — ตั้งแต่ 4c8aa71 สร้างเมื่อกดปุ่ม
- summary: สรุปผลด้วย Gemini ด้วยฟังก์ชันเดิม (summary.py) · report: ไฟล์ Word/PowerPoint ด้วยตัวสร้างเดิม (reports.py) — Step 7
store ต้องมี add_dataset/dataset/ecm/save_ecm/series/save_series (db.py หรือ store_memory.py)
"""
import base64
import contextlib
import datetime
import inspect
import time
from typing import Optional

from google import genai

from . import codec, compute, config, data_loader, gemini_fixture, reports, summary
from .data_loader import load_data_gsheet
from .modeling import tfp
from .sheets_fixture import maybe_fixture


# ย้ายจาก TFP_App1.3.0.py:91-107 (e6aee03) — เดิมเรียกในหน้าเว็บตอนกดปุ่มดึงข้อมูล
def _load_data_gsheet_with_optional_url(url: Optional[str] = None):
    """เรียก load_data_gsheet() ตามปกติ แต่ถ้าคณะวิจัยกรอกลิงก์ Google Sheet เอง
    ไว้ในหน้า "จัดการข้อมูลอัตโนมัติ" (เก็บใน session_state["custom_gsheet_url"])
    จะส่งลิงก์นั้นเข้าไปให้ load_data_gsheet(url=...) ด้วย (data_loader.py
    รองรับพารามิเตอร์ url ที่รับได้ทั้งลิงก์ Google Sheet เต็มรูปแบบและ Sheet ID
    ล้วนๆ — ถ้าไม่ได้กรอกอะไรมา จะใช้ SHEET_ID เริ่มต้นในไฟล์ data_loader.py แทน)"""
    if not url:
        return load_data_gsheet()
    try:
        sig_params = inspect.signature(load_data_gsheet).parameters
    except (TypeError, ValueError):
        sig_params = {}
    for param_name in ("url", "sheet_url", "gsheet_url", "link"):
        if param_name in sig_params:
            return load_data_gsheet(**{param_name: url})
    # ฟังก์ชันเดิมยังไม่รองรับการกำหนดลิงก์เอง -> ใช้ค่าเริ่มต้นในไฟล์ data_loader.py ไปก่อน
    return load_data_gsheet()


@contextlib.contextmanager
def _sheets_timeout(seconds: float):
    """หน้าเดิมไม่มี timeout (ชีตค้าง = หน้าของผู้ใช้คนนั้นค้าง) แต่ระบบใหม่มี worker ตัวเดียวทำงานของทุกคน งานดึงชีตที่ค้าง
    จะทำให้งานอื่นรอทั้งหมด จึงตั้ง timeout ต่อคำขอ HTTP ของ client ที่ loader สร้าง (gspread Client.set_timeout;
    แผน §16 timeout ของบริการภายนอก, §20.3) — ไม่แก้ loader เดิม"""
    real = data_loader._get_client

    def get_client():
        client = real()
        client.set_timeout(seconds)
        return client

    data_loader._get_client = get_client
    try:
        yield
    finally:
        data_loader._get_client = real


@contextlib.contextmanager
def _bound(module, **names):
    """ตั้งชื่อระดับโมดูลของโค้ดที่ย้ายมาชั่วคราวแล้วคืนค่าเดิม (worker ทำทีละ job จึงไม่ชนกัน)"""
    old = {k: getattr(module, k) for k in names}
    for k, v in names.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(module, k, v)


class _Stop(BaseException):
    """st.stop() ใน generate_summary_gemini — หยุดแบบเดียวกับ Streamlit (ไม่ถูก except Exception ของโค้ดเดิมจับ)"""


class _StRecorder:
    """แทน st ของ generate_summary_gemini (เรียกเฉพาะ st.error(ข้อความ) และ st.stop()) — ส่งกลับไปแสดงที่หน้าเว็บ"""

    def __init__(self):
        self.errors = []

    def error(self, body):
        self.errors.append(body)

    def stop(self):
        raise _Stop()


def _summary(store, params) -> dict:
    """สรุปผลด้วย Gemini (TFP_App1.3.0.py:4423) — fit ECM ชุดตัวแปรเดียวกับหน้า (ผล statsmodels จริงพร้อมผลทดสอบ
    Engle-Granger ที่ _eg_text ใช้) แล้วเรียก generate_summary_gemini ตัวเดิม; ไม่มี dedupe จึงไม่ถูกเรียกซ้ำอัตโนมัติ
    เมื่อ worker หาย (แผน §10) — done_at = เวลาที่ Gemini ตอบ (หน้าเดิมทำต่อทันทีหลังได้คำตอบ)"""
    model_df = tfp.build_model_frame(store.dataset(params["dataset_id"]))
    dep_ln = "ln_" + tfp.DEP_VAR
    lr_res, lr_resid = compute._quiet(tfp.run_long_run, model_df, dep_ln, list(params["lr_vars"]))
    sr_res = compute._quiet(tfp.run_short_run, model_df, dep_ln, [tuple(s) for s in params["sr_spec"]], lr_resid)
    client = gemini_fixture.client(lambda: genai.Client(api_key=config.secrets()["GEMINI_API_KEY"]))
    rec = _StRecorder()
    with _bound(summary, gemini_client=client, st=rec):
        try:
            text = compute._quiet(summary.generate_summary_gemini, lr_res, sr_res, model_df, dep_ln)
        except _Stop:
            text = None
    return {"text": text, "errors": rec.errors, "stopped": text is None, "done_at": time.time()}


def _report(params) -> dict:
    """ไฟล์ Word/PowerPoint (TFP_App1.3.0.py:4447-4456) ด้วยตัวสร้างเดิม — เวลา "สร้างเมื่อวันที่" ในไฟล์ = เวลาที่หน้าเว็บ
    แสดงใต้บทสรุป (params["now"]; หน้าเดิมสร้างไฟล์ในรอบเดียวกัน)"""
    build = {"word": reports.build_word_report, "pptx": reports.build_pptx_report}[params["report"]]
    now = datetime.datetime.fromisoformat(params["now"])
    with _bound(reports, now_th=lambda: now):
        data = compute._quiet(build, *codec.decode(params["args"]), **codec.decode(params["kwargs"]))
    return {"b64": base64.b64encode(data).decode("ascii")}


def ensure_default_results(store, dataset_id) -> None:
    raw = store.dataset(dataset_id)
    lr, sr = list(tfp.LONG_RUN_VARS), list(tfp.SHORT_RUN_SPEC)
    if store.ecm(dataset_id, lr, sr) is None:
        store.save_ecm(dataset_id, lr, sr, compute.ecm_bundle(raw, lr, sr))
    # backtest (series) ไม่คำนวณต่อท้ายการดึงข้อมูลแล้ว: ต้นฉบับ 4c8aa71 คำนวณเมื่อผู้ใช้กดปุ่ม "เริ่มการทดสอบย้อนหลัง"
    # (rolling ใช้ราว 85 วินาทีบน Mac) — หน้าเว็บสร้าง job series เองเมื่อกดปุ่ม (page_api._backtest_with_file_cache)


def execute(store, kind: str, params: dict) -> dict:
    """ทำงานหนึ่ง job คืน result (JSON) — exception ที่หลุดออกไปถือว่า job ล้มเหลว (worker บันทึกชนิด+ข้อความ)"""
    if kind == "fetch":
        with _sheets_timeout(config.settings().sheets_timeout_seconds), maybe_fixture():
            raw = _load_data_gsheet_with_optional_url(params.get("url"))
        read_at = time.time()  # หน้าเดิมบันทึกเวลา now_th() ทันทีหลังอ่านเสร็จ (TFP_App1.3.0.py:3228, 6660)
        dataset_id = store.add_dataset(raw, source={"url": params.get("url")})
        ensure_default_results(store, dataset_id)
        return {"dataset_id": dataset_id, "read_at": read_at}
    if kind == "ecm":
        lr, sr = params["lr_vars"], [tuple(s) for s in params["sr_spec"]]
        if store.ecm(params["dataset_id"], lr, sr) is None:
            store.save_ecm(params["dataset_id"], lr, sr, compute.ecm_bundle(store.dataset(params["dataset_id"]), lr, sr))
        return {}
    if kind == "series":
        if store.series(params["dataset_id"]) is None:
            store.save_series(params["dataset_id"], compute.series_bundle(store.dataset(params["dataset_id"])))
        return {}
    if kind == "summary":
        return _summary(store, params)
    if kind == "report":
        return _report(params)
    raise ValueError(f"ไม่รู้จักงานชนิด {kind}")
