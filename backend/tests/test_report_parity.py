"""Step 7 เกณฑ์ A: Gemini และรายงาน — ผลของระบบใหม่ต้องเหมือนโค้ดต้นฉบับ (root ของ workspace, 7bf84e4) บน runtime เดียวกัน

ฝั่งเดิม: generate_summary_gemini / build_word_report / build_pptx_report และตัวช่วย exec จาก AST ของ TFP_App1.3.0.py
พร้อมผล fit จาก TFP.py ต้นฉบับ (ไฟล์ภาพ/ฟอนต์ที่ root ของต้นฉบับ) · ฝั่งใหม่: jobs.execute("summary"/"report") ตัวที่ worker ใช้
ทั้งสองฝั่งใช้ client ของโหมดทดสอบตัวเดียวกัน (gemini_fixture: คำตอบสังเคราะห์ ไม่ใช่ผล Gemini จริง ไม่มีคำขอออกอินเทอร์เน็ต)
- Gemini: คำขอทุกครั้ง (model, prompt, system instruction), ข้อความที่คืน, ข้อความ st.error, การหยุด, จำนวนครั้งที่ลองใหม่
  และเวลารอ (time.sleep ถูกแทนด้วยตัวบันทึก) — กรณีสำเร็จ, 429/503 ทุกครั้ง, 400, 503 แล้วสำเร็จ × ชุดตัวแปร 2 ชุด
- Word/PowerPoint: ทุก part ใน ZIP ตรงกันทุก byte (ไม่ใช้ hash ของ ZIP — วันที่ของ entry ใน ZIP ต่างตามเวลาที่บันทึก)
  เวลา "สร้างเมื่อวันที่" ตรึงค่าเดียวกันทั้งสองฝั่ง; PowerPoint ฝังไฟล์ Excel ของกราฟ (python-pptx สร้างด้วย xlsxwriter) ที่บันทึก
  เวลาสร้างระดับวินาทีใน docProps/core.xml ของไฟล์ฝัง — ไฟล์ของต้นฉบับเองก็ต่างกันทุกวินาที จึงตรึงเวลาของ xlsxwriter เท่ากันด้วย
ไม่มี expected ที่เขียนเอง ผลอ้างอิงคือผลของโค้ดต้นฉบับในรอบเดียวกัน
"""
import base64
import datetime
import io
import json
import math
import os
import re
import sys
import zipfile
from datetime import timedelta, timezone

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import pytest
import xlsxwriter.core
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement as docx_OxmlElement
from docx.oxml.ns import qn as docx_qn
from docx.shared import Mm as DocxMm, Pt as DocxPt, RGBColor as DocxRGBColor
from google.genai import types
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_MARKER_STYLE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph

import parity
from test_parity_cases import exec_nodes, load_df_raw, load_original

from app import codec, gemini_fixture, jobs, summary
from app.modeling import tfp
from app.store_memory import MemoryStore

REPO = parity.REPO
sys.path.insert(0, str(REPO / "tools" / "refactor"))
from extract_page import GEMINI, REPORTS  # noqa: E402
from extract_reports import REPORTS_COPIES, SUMMARY_COPIES  # noqa: E402

FIXTURE = REPO / "backend" / "tests" / "fixtures" / "gemini_synthetic.json"
SYNTHETIC = json.loads(FIXTURE.read_text(encoding="utf-8"))["responses"][0]["text"]
FIXED_NOW = datetime.datetime(2026, 10, 10, 21, 7, 0)


class _FixedUtcNow(datetime.datetime):
    """เวลาของ xlsxwriter (xlsxwriter.core: datetime.now(timezone.utc)) ระหว่างสร้างไฟล์ทั้งสองฝั่ง"""

    @classmethod
    def now(cls, tz=None):
        return datetime.datetime(2026, 10, 10, 14, 7, 0, tzinfo=datetime.timezone.utc)
VAR_SETS = [
    ("ค่าเริ่มต้น", list(tfp.LONG_RUN_VARS), list(tfp.SHORT_RUN_SPEC)),
    ("ตัด MKTCOM ระยะยาว + ตัดตัวแรกระยะสั้น", [v for v in tfp.LONG_RUN_VARS if v != "MKTCOM"], list(tfp.SHORT_RUN_SPEC)[1:]),
]


def _err(code, status, message):
    return {"error": {"code": code, "response_json": {"error": {"code": code, "message": message, "status": status}}}}


E429 = _err(429, "RESOURCE_EXHAUSTED", "synthetic test error (not from Gemini)")
E503 = _err(503, "UNAVAILABLE", "synthetic test error (not from Gemini)")
E400 = _err(400, "INVALID_ARGUMENT", "synthetic test error (not from Gemini)")
CASES = {
    "สำเร็จ": [{"text": SYNTHETIC}],
    "429 ทุกครั้ง": [E429],
    "503 ทุกครั้ง": [E503],
    "400": [E400],
    "503 สองครั้งแล้วสำเร็จ": [E503, E503, {"text": SYNTHETIC}],
}


class _Sleeps:
    """แทน time ในฟังก์ชันเดิม: บันทึกเวลารอแทนการรอจริง"""

    def __init__(self):
        self.delays = []

    def sleep(self, s):
        self.delays.append(s)


class _OrigStop(BaseException):
    pass


class _OrigSt:
    def __init__(self):
        self.errors = []

    def error(self, body):
        self.errors.append(body)

    def stop(self):
        raise _OrigStop()


@pytest.fixture(scope="module")
def original():
    o = load_original()
    T, F = o["T"], o["F"]
    names = list(dict.fromkeys(GEMINI + SUMMARY_COPIES + REPORTS + REPORTS_COPIES))
    ns = exec_nodes(REPO / "TFP_App1.3.0.py", names, {
        "pd": pd, "math": math, "os": os, "re": re, "BytesIO": io.BytesIO, "datetime": datetime.datetime,
        "timezone": timezone, "timedelta": timedelta, "matplotlib": matplotlib, "plt": plt, "fm": fm, "types": types,
        "Paragraph": Paragraph, "pdfmetrics": pdfmetrics, "TTFont": TTFont, "Presentation": Presentation,
        "Inches": Inches, "Pt": Pt, "RGBColor": RGBColor, "PP_ALIGN": PP_ALIGN, "MSO_ANCHOR": MSO_ANCHOR,
        "CategoryChartData": CategoryChartData, "XL_CHART_TYPE": XL_CHART_TYPE, "XL_MARKER_STYLE": XL_MARKER_STYLE,
        "Document": Document, "DocxPt": DocxPt, "DocxMm": DocxMm, "DocxRGBColor": DocxRGBColor,
        "WD_ALIGN_PARAGRAPH": WD_ALIGN_PARAGRAPH, "WD_TABLE_ALIGNMENT": WD_TABLE_ALIGNMENT,
        "docx_qn": docx_qn, "docx_OxmlElement": docx_OxmlElement,
        # ชื่อที่แอปเดิม import จาก TFP และ _merge_coefficient_tables (โค้ดเดิมของแอป) — จากต้นฉบับทั้งหมด
        "build_coefficient_tables": T.build_coefficient_tables, "build_tfpi_yoy_summary": T.build_tfpi_yoy_summary,
        "summary_adj_r2": T.summary_adj_r2, "DEP_VAR": T.DEP_VAR,
        "_merge_coefficient_tables": F["_merge_coefficient_tables"],
        # ที่ตั้งไฟล์ภาพ/ฟอนต์ของแอปเดิม = โฟลเดอร์ของ TFP_App1.3.0.py (TFP_App1.3.0.py:122-123)
        "APP_DIR": str(REPO), "FONT_DIR": os.path.join(str(REPO), "fonts")})
    return {"T": T, "ns": ns}


@pytest.fixture(scope="module")
def data():
    raw = load_df_raw()
    store = MemoryStore()
    return {"raw": raw, "store": store, "dataset_id": store.add_dataset(raw)}


def _original_fit(original, raw, lr_vars, sr_spec):
    T = original["T"]
    model_df = T.build_model_frame(raw)
    dep_ln = "ln_" + T.DEP_VAR
    lr_res, lr_resid = T.run_long_run(model_df, dep_ln, list(lr_vars))
    sr_res = T.run_short_run(model_df, dep_ln, list(sr_spec), lr_resid)
    return model_df, dep_ln, lr_res, sr_res


def _run_original_summary(original, raw, lr_vars, sr_spec, responses):
    ns = original["ns"]
    model_df, dep_ln, lr_res, sr_res = _original_fit(original, raw, lr_vars, sr_spec)
    st, sleeps = _OrigSt(), _Sleeps()
    gemini_fixture.CALLS.clear()
    ns.update(gemini_client=gemini_fixture.FixtureClient(responses), st=st, time=sleeps)
    try:
        text = ns["generate_summary_gemini"](lr_res, sr_res, model_df, dep_ln)
    except _OrigStop:
        text = None
    return {"text": text, "errors": st.errors, "stopped": text is None, "calls": list(gemini_fixture.CALLS),
            "delays": sleeps.delays}


def _run_new_summary(data, lr_vars, sr_spec, responses, tmp_path, monkeypatch):
    path = tmp_path / "gemini.json"
    path.write_text(json.dumps({"note": "synthetic", "responses": responses}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("TFP_GEMINI_FIXTURE", str(path))
    sleeps = _Sleeps()
    monkeypatch.setattr(summary, "time", sleeps)
    gemini_fixture.CALLS.clear()
    r = jobs.execute(data["store"], "summary", {"dataset_id": data["dataset_id"], "lr_vars": list(lr_vars),
                                                "sr_spec": [list(s) for s in sr_spec]})
    assert isinstance(r["done_at"], float)
    return {"text": r["text"], "errors": r["errors"], "stopped": r["stopped"], "calls": list(gemini_fixture.CALLS),
            "delays": sleeps.delays}


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("var_set", VAR_SETS, ids=[v[0] for v in VAR_SETS])
def test_gemini_summary_matches_original(original, data, case, var_set, tmp_path, monkeypatch):
    _, lr_vars, sr_spec = var_set
    old = _run_original_summary(original, data["raw"], lr_vars, sr_spec, CASES[case])
    new = _run_new_summary(data, lr_vars, sr_spec, CASES[case], tmp_path, monkeypatch)
    assert new == old
    assert old["calls"] and old["calls"][0]["model"] == "gemini-2.5-flash"
    if case == "สำเร็จ":
        assert old["text"] == SYNTHETIC and not old["errors"]
    else:
        assert len(old["calls"]) == {"429 ทุกครั้ง": 5, "503 ทุกครั้ง": 5, "400": 1, "503 สองครั้งแล้วสำเร็จ": 3}[case]


def _report_inputs(original, data):
    model_df, dep_ln, lr_res, sr_res = _original_fit(original, data["raw"], *VAR_SETS[0][1:])
    T = original["T"]
    lr_table, sr_table = T.build_coefficient_tables(lr_res, sr_res)
    return [SYNTHETIC, lr_table, sr_table, T.summary_adj_r2(lr_res), T.summary_adj_r2(sr_res), model_df]


def _parts(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return {name: z.read(name) for name in z.namelist()}


@pytest.mark.parametrize("kind,fn", [("word", "build_word_report"), ("pptx", "build_pptx_report")])
def test_report_file_matches_original(original, data, kind, fn, monkeypatch):
    monkeypatch.setattr(xlsxwriter.core, "datetime", _FixedUtcNow)
    args = _report_inputs(original, data)
    ns = original["ns"]
    real_now_th = ns["now_th"]
    ns["now_th"] = lambda: FIXED_NOW
    try:
        old = ns[fn](*args)
    finally:
        ns["now_th"] = real_now_th
    r = jobs.execute(data["store"], "report", {"report": kind, "args": codec.encode(args), "kwargs": codec.encode({}),
                                               "now": FIXED_NOW.isoformat()})
    new = base64.b64decode(r["b64"])
    old_parts, new_parts = _parts(old), _parts(new)
    assert list(old_parts) == list(new_parts)
    differ = [name for name in old_parts if old_parts[name] != new_parts[name]]
    assert not differ, f"part ที่ต่าง: {differ}"
    # เวลาที่ตรึงไว้อยู่ในไฟล์จริง (ข้อความ "สร้างเมื่อวันที่ 10 ตุลาคม 2569 เวลา 21:07 น.")
    assert any("21:07".encode() in blob for blob in new_parts.values())
