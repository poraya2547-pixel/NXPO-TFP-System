"""Step 7: สร้าง backend/app/summary.py (Gemini) และ backend/app/reports.py (Word/PowerPoint) จากโค้ดหน้าเดิม
TFP_App1.3.0.py ที่ root ของ workspace (7bf84e4) แบบคัดลอกทั้งก้อน — ห้ามทับไฟล์ที่มีอยู่ ห้ามแก้ไฟล์ที่สร้างด้วยมือ

- ชื่อที่ "ย้าย" (ถูกตัดออกจาก page_script.py ตั้งแต่ Step 3: extract_page.GEMINI / REPORTS) อยู่ในไฟล์ใหม่ที่เดียว
- ชื่อที่ "คัดลอก" (หน้าเว็บยังใช้อยู่ จึงคงไว้ใน page_script.py ด้วย): GEMINI_MODEL, TH_TZ, now_th, THAI_MONTHS,
  thai_timestamp, _web_summary_text — เนื้อโค้ดเหมือนต้นฉบับ
- หัวไฟล์ import ชื่อเดียวกับที่หน้าเดิม import (TFP_App1.3.0.py:18-91) เฉพาะที่ฟังก์ชันชุดนี้ใช้
ตรวจซ้ำด้วย backend/tests/test_moved_reports.py (เนื้อโค้ด) และ test_report_parity.py (ผลเทียบต้นฉบับ)

    /opt/anaconda3/envs/idntwww/bin/python -B tools/refactor/extract_reports.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "baseline"))
sys.path.insert(0, str(REPO / "tools" / "refactor"))
import safe_io  # noqa: E402
from extract_core import APP, SOURCE_COMMIT, segment, top_level  # noqa: E402
from extract_page import GEMINI, REPORTS  # noqa: E402

SUMMARY_COPIES = ["GEMINI_MODEL"]
REPORTS_COPIES = ["TH_TZ", "now_th", "GEMINI_MODEL", "THAI_MONTHS", "thai_timestamp", "_web_summary_text"]

SUMMARY_HEAD = f'''"""สรุปผลด้วย Gemini — ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit {SOURCE_COMMIT})
สร้างด้วย tools/refactor/extract_reports.py ห้ามแก้ด้วยมือ

prompt, ชื่อโมเดล, การลองใหม่ และข้อความแจ้งผู้ใช้เหมือนต้นฉบับทุกตัวอักษร (GEMINI_MODEL เป็นสำเนา — หน้าเว็บยังใช้ใน footer)
ต่างจากต้นฉบับเพียง 2 ชื่อที่หน้าเดิมสร้างตอนเปิดแอป: gemini_client (TFP_App1.3.0.py:1688-1696) และ st (streamlit)
ซึ่ง worker ตั้งให้ต่อ job (jobs.py) — ฟังก์ชันรันใน worker ด้วยผล fit ของ statsmodels จริงแบบหน้าเดิม
"""
import time

import pandas as pd
from google.genai import types

from .modeling.tfp import build_coefficient_tables, build_tfpi_yoy_summary, summary_adj_r2

gemini_client = None  # worker ตั้งต่อ job: genai.Client(api_key=...) ของค่าลับเดิม หรือ client ของโหมดทดสอบ
st = None             # worker ตั้งต่อ job: ตัวบันทึก st.error / st.stop ส่งกลับไปแสดงที่หน้าเว็บ


'''

REPORTS_HEAD = f'''"""ไฟล์รายงาน Word/PowerPoint — ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit {SOURCE_COMMIT})
สร้างด้วย tools/refactor/extract_reports.py ห้ามแก้ด้วยมือ

ตัวสร้างไฟล์ ตัวช่วย และค่าคงที่เหมือนต้นฉบับทั้งก้อน; ชื่อที่หน้าเว็บยังใช้ (GEMINI_MODEL, TH_TZ, now_th, THAI_MONTHS,
thai_timestamp, _web_summary_text) เป็นสำเนา — APP_DIR/FONT_DIR ชี้ไฟล์ภาพ/ฟอนต์ชุดเดียวกับหน้าเว็บ (backend/app/assets
สำเนาทุก byte ของไฟล์ที่ root ต้นฉบับ) worker เรียกใน job report (jobs.py) โดยให้ now_th คืนเวลาที่หน้าเว็บแสดง
(หน้าเดิมสร้างไฟล์ในรอบเดียวกับข้อความ "สร้างเมื่อวันที่ …" ใต้บทสรุป)
"""
import math
import os
import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.font_manager as fm  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.platypus import Paragraph  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR  # noqa: E402
from pptx.chart.data import CategoryChartData  # noqa: E402
from pptx.enum.chart import XL_CHART_TYPE, XL_MARKER_STYLE  # noqa: E402
from docx import Document  # noqa: E402
from docx.shared import Pt as DocxPt, Mm as DocxMm, RGBColor as DocxRGBColor  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.oxml.ns import qn as docx_qn  # noqa: E402
from docx.oxml import OxmlElement as docx_OxmlElement  # noqa: E402

from .modeling.core import _merge_coefficient_tables  # noqa: E402
from .modeling.tfp import DEP_VAR  # noqa: E402

# ที่ตั้งไฟล์แอปของหน้าเดิม (TFP_App1.3.0.py:122-123) = โฟลเดอร์ภาพ/ฟอนต์ที่หน้าเว็บใหม่ใช้ (page_runner.ASSETS_DIR)
APP_DIR = str(Path(__file__).resolve().parent / "assets")
FONT_DIR = os.path.join(APP_DIR, "fonts")


'''


def build(src, nodes, moved, copied) -> str:
    parts = []
    for name in sorted(moved + copied, key=lambda n: nodes[n].lineno):
        node = nodes[name]
        text = segment(src, node)
        if text.lstrip().startswith("@"):
            raise RuntimeError(f"{name} มี decorator ที่ไม่ได้คาดไว้")
        how = "คัดลอก" if name in copied else "ย้าย"
        parts.append(f"# {how}จาก TFP_App1.3.0.py:{node.lineno}-{node.end_lineno} ({SOURCE_COMMIT})\n{text}")
    return "\n\n".join(parts) + "\n"


def main():
    src = APP.read_text(encoding="utf-8")
    nodes = top_level(src)
    missing = sorted(set(GEMINI + REPORTS + SUMMARY_COPIES + REPORTS_COPIES) - set(nodes))
    if missing:
        raise RuntimeError(f"ไม่พบ {missing}")
    targets = {
        REPO / "backend" / "app" / "summary.py": SUMMARY_HEAD + build(src, nodes, GEMINI, SUMMARY_COPIES),
        REPO / "backend" / "app" / "reports.py": REPORTS_HEAD + build(src, nodes, REPORTS, REPORTS_COPIES),
    }
    safe_io.ensure_absent(list(targets))
    for path, text in targets.items():
        compile(text, str(path), "exec")
        safe_io.write_new(path, text)
        print("เขียนแล้ว", path.relative_to(REPO), f"({len(text.splitlines())} บรรทัด)")


if __name__ == "__main__":
    main()
