"""
================================================================================
เว็บแอป TFP Executive Summary (Streamlit + Gemini API)
================================================================================
วิธีรัน:
    streamlit run app.py

ต้องมีไฟล์ .streamlit/secrets.toml อยู่ในโฟลเดอร์เดียวกับ app.py นี้ โดยข้างในมี:
    GEMINI_API_KEY = "ใส่ key จริงตรงนี้"

ติดตั้ง library ที่ต้องใช้ (ถ้ายังไม่มี):
    pip install streamlit google-genai pandas numpy statsmodels openpyxl scipy reportlab python-pptx python-docx matplotlib

หมายเหตุ: ไฟล์นี้ใช้โมเดล gemini-2.5-flash
================================================================================
"""

import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import base64
import hmac
import os
import csv
import re
import math
import time
import warnings
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from io import BytesIO
from datetime import datetime, timezone, timedelta

# เซิร์ฟเวอร์ของแอปมักตั้งเวลาไว้เป็น UTC (ไม่ใช่เวลาไทย) ทำให้เวลาที่แสดงในแอป
# (เช่น "ดึงข้อมูลล่าสุดเมื่อ") ช้ากว่าเวลาจริง 7 ชั่วโมง — ใช้ TH_TZ แทน datetime.now()
# ทุกจุดที่ต้องการแสดงเวลาให้ผู้ใช้เห็น เพื่อให้ตรงกับเวลาประเทศไทย (UTC+7)
TH_TZ = timezone(timedelta(hours=7))


def now_th() -> datetime:
    """คืนค่าเวลาปัจจุบันตามเวลาประเทศไทย (UTC+7) แบบ naive datetime
    (ตัด tzinfo ออกเพื่อให้ยังใช้ .strftime() ต่อได้เหมือนโค้ดเดิมทุกจุด)"""
    return datetime.now(TH_TZ).replace(tzinfo=None)
from google import genai
from google.genai import types
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller
from statsmodels.tools.sm_exceptions import ConvergenceWarning

# ปิด warning จาก statsmodels ตอนลองหาค่า (p,d,q) หลายชุดของ ARIMA (auto-search)
# เพราะบางชุดค่าไม่ converge/ไม่เหมาะกับข้อมูล ซึ่งเป็นเรื่องปกติของการลอง grid search
warnings.simplefilter("ignore", ConvergenceWarning)
warnings.simplefilter("ignore", UserWarning)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_MARKER_STYLE
from docx import Document
from docx.shared import Pt as DocxPt, Mm as DocxMm, RGBColor as DocxRGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn as docx_qn
from docx.oxml import OxmlElement as docx_OxmlElement

from TFP import (
    build_model_frame, run_long_run, run_short_run,
    build_coefficient_tables, build_tfpi_yoy_summary, summary_adj_r2,
    adf_report, run_diagnostics, LONG_RUN_VARS, SHORT_RUN_SPEC, DEP_VAR,
)
from data_loader import load_data_gsheet
import inspect
from typing import Optional


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

st.set_page_config(page_title="ระบบวิเคราะห์ผลิตภาพปัจจัยการผลิตรวม", layout="wide")

# ------------------------------------------------------------------------------
# ฟอนต์ — เปลี่ยนหน้าเว็บให้ใช้ 'Prompt' (ฟอนต์ Thai sans-serif ที่เว็บ สอวช./NXPO
# ใช้จริง ตามภาพตัวอย่างที่ผู้ใช้ส่งมา) เป็นฟอนต์หลัก โดยยังคง Sarabun ไว้เป็น
# ฟอนต์สำรอง (ใช้กรณีโหลด Google Fonts ไม่ได้ และยังใช้กับไฟล์ PDF/PPTX ที่ export
# อยู่เดิม เพราะไฟล์ .ttf ของ Sarabun ฝังอยู่ในเครื่องอยู่แล้ว)
#
# หากต้องการเปลี่ยนฟอนต์อีกในอนาคต แก้แค่ตัวแปร FONT_FAMILY ตัวเดียวด้านล่างนี้
# (ต้องเป็นชื่อฟอนต์ที่มีบน Google Fonts และรองรับภาษาไทย เช่น Prompt, Kanit,
# IBM Plex Sans Thai, Noto Sans Thai)
# ------------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "."
FONT_DIR = os.path.join(APP_DIR, "fonts")
FONT_FAMILY = "Prompt"  # <-- เปลี่ยนชื่อฟอนต์ตรงนี้ที่เดียวถ้าอยากเปลี่ยนฟอนต์ทั้งเว็บ


def _font_b64(filename: str) -> str:
    with open(os.path.join(FONT_DIR, filename), "rb") as f:
        return base64.b64encode(f.read()).decode()


st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family={FONT_FAMILY.replace(" ", "+")}:wght@300;400;500;600;700;800&display=swap');

    /* ใช้ * แทน selector รายชื่อ class เดิม เพื่อให้ครอบคลุมทุก element ของ
       Streamlit จริงๆ (ปุ่ม, input, dropdown, expander, dataframe, tab,
       sidebar ฯลฯ ที่ปกติมี class เฉพาะของตัวเอง override ฟอนต์ default ทับอยู่) */
    html, body, * {{
        font-family: '{FONT_FAMILY}', 'Sarabun', sans-serif !important;
    }}

    /* ไอคอน/ฟอนต์ตัวเลขบางตัวของ Streamlit (เช่น Material Icons/Symbols ใน
       ปุ่ม expander ▶, multiselect X, ฯลฯ) ใช้ font เฉพาะของมันเอง (ligature
       font ที่แปลงคำว่า "keyboard_arrow_right" ให้กลายเป็นรูปลูกศร) ถ้าโดน
       !important ด้านบนบังคับเป็น Prompt จะไม่ใช่ ligature อีกต่อไป กลายเป็น
       ข้อความ "arrow_right" ปนกับ label ตรงๆ จึงต้องกันไว้ให้ครอบคลุมทุกแบบ
       ที่ Streamlit ใช้ (ชื่อ class/attribute เปลี่ยนไปตามเวอร์ชัน) */
    [class*="material-icons" i],
    [class*="material-symbols" i],
    [class*="MaterialIcon" i],
    [data-testid*="Icon" i],
    [data-testid="stExpanderToggleIcon"],
    [data-testid="stIconMaterial"] {{
        font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    _regular_b64 = _font_b64("Sarabun-Regular.ttf")
    _bold_b64 = _font_b64("Sarabun-Bold.ttf")
    st.markdown(f"""
    <style>
    @font-face {{
        font-family: 'Sarabun';
        src: url(data:font/ttf;base64,{_regular_b64}) format('truetype');
        font-weight: 400;
    }}
    @font-face {{
        font-family: 'Sarabun';
        src: url(data:font/ttf;base64,{_bold_b64}) format('truetype');
        font-weight: 700;
    }}
    </style>
    """, unsafe_allow_html=True)
except FileNotFoundError:
    # ไม่เจอไฟล์ .ttf ของ Sarabun ในเครื่อง -> ไม่เป็นไร เพราะฟอนต์หลักคือ
    # Prompt จาก Google Fonts CDN ด้านบนอยู่แล้ว (Sarabun ใช้เป็นแค่ fallback)
    pass
# ------------------------------------------------------------------------------
# ธีมสี / การ์ด / badge / sidebar ของแดชบอร์ด และแก้ปัญหา multiselect ตัดชื่อ
# ตัวแปรด้วย "..." (ค่าเริ่มต้นของ Streamlit/BaseWeb จำกัดความกว้างของแท็กที่เลือกไว้
# ทำให้ชื่อเต็มของตัวแปรถูกตัดจนอ่านไม่รู้เรื่อง — CSS ด้านล่างแก้ปัญหานี้ไปพร้อมกัน)
# ------------------------------------------------------------------------------
st.markdown("""
<style>
:root {
    /* กลับมาใช้ธีมส้มเดิม (สีเดียวกับที่ใช้งานจริงบน Streamlit Cloud) ตัวแปรอื่น
       ที่อ้างอิง --brand-orange / --brand-orange-dark ทั่วทั้งไฟล์จะเปลี่ยนสี
       ตามอัตโนมัติโดยไม่ต้องแก้จุดอื่น — ปรับให้อ่อนลงอีกนิดตามที่ขอ */
    --brand-orange: #F97316;
    --brand-orange-dark: #C2410C;
    --brand-navy: #16324A;
    --brand-navy-soft: #5B6B7C;
    --bg-page: #F7F5F1;
    --card-border: #E7E1D6;
    --gold-tint: #F6EFDC;
    --green: #16A34A;
    --amber: #F59E0B;
    --red: #EF4444;
    --blue: #2F6FED;
    --font-elegant: 'Noto Serif Thai', 'Prompt', serif;
    --shadow-soft: 0 4px 16px rgba(22,50,74,0.07), 0 1.5px 4px rgba(22,50,74,0.05);
    --shadow-lift: 0 16px 36px rgba(22,50,74,0.13), 0 4px 10px rgba(22,50,74,0.07);
}
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+Thai:wght@500;600&display=swap');
.stApp {
    /* พื้นหลังไล่เฉดครีมเบา ๆ + จุดไล่สีทองจางมากที่มุมบน + ลายจุดตารางแบบบางๆ
       (dot-grid) ให้พื้นหลังมีเนื้อสัมผัสแบบแดชบอร์ดข้อมูลมืออาชีพ โดยยังคงให้
       การ์ดสีขาวด้านบน "ลอยเด่น" ขึ้นมาจากพื้นแทนที่จะกลืนไปกับมัน */
    background:
        radial-gradient(1100px 480px at 12% -6%, rgba(201,154,75,0.09), transparent 60%),
        radial-gradient(900px 420px at 100% 0%, rgba(22,50,74,0.045), transparent 55%),
        radial-gradient(rgba(22,50,74,0.05) 1px, transparent 1px),
        linear-gradient(180deg, #FAF8F4 0%, var(--bg-page) 320px);
    background-size: auto, auto, 24px 24px, auto;
}

/* ----- แถบหัวเว็บเริ่มต้นของ Streamlit (เมนู "..."/ปุ่ม Deploy) — เป็นตัวการที่
   ทำให้เกิดพื้นที่ว่างสีขาวโล่งๆ ด้านบนสุดของหน้าเว็บ (ทั้งฝั่งแถบเมนูซ้ายและ
   เนื้อหาหลัก) เพราะปกติ Streamlit เผื่อพื้นที่ด้านบนไว้ให้แถบนี้เสมอ แอปนี้มี
   แถบเมนู/หัวข้อของตัวเองอยู่แล้ว (nxpo-topbar) จึงซ่อนแถบเริ่มต้นนี้ทิ้งไปเลย
   และลด padding-top ของเนื้อหาหลักที่เผื่อพื้นที่ไว้ให้แถบนี้ลงด้วย ----- */
header[data-testid="stHeader"] {
    height: 0rem !important;
    min-height: 0rem !important;
    visibility: hidden;
}
[data-testid="stMain"] .block-container {
    padding-top: 1.5rem !important;
}

/* ----- ปุ่ม >> ย่อ/ขยาย sidebar (collapsedControl) — เปลี่ยนพื้นหลังเป็นสีส้ม
   ตามธีมหลักของแอป (--brand-orange) แทนสีเทาเดิมของ Streamlit ----- */
[data-testid="collapsedControl"] {
    background-color: var(--brand-orange) !important;
    border-radius: 8px;
}
[data-testid="collapsedControl"] svg {
    color: #FFFFFF !important;
}
[data-testid="collapsedControl"]:hover {
    background-color: var(--brand-orange-dark) !important;
}

/* ----- sidebar: พื้นขาวตามปกติ ไฮไลต์ส้มเฉพาะเมนูที่กำลังเลือกอยู่ ----- */
section[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid var(--card-border);
}
section[data-testid="stSidebar"] .block-container {
    /* เดิม padding-top: 1.2rem; ผู้ใช้ขอให้ขยับเนื้อหา (โลโก้/ปุ่ม) ข้างในแถบเมนู
       ขึ้นอีก 10มม. ให้ชิดขอบบนมากขึ้น เนื่องจาก padding เป็นค่าติดลบไม่ได้
       จึงตัด padding-top ออกแล้วใช้ margin-top ติดลบแทน (คำนวณ: 1.2rem - 10mm) */
    padding-top: 0;
    margin-top: calc(1.2rem - 10mm);
}
section[data-testid="stSidebar"] [data-testid="stAlert"] * { color: inherit !important; }

/* ----- มือถือ/จอแคบ: ฟิกแถบเมนูด้านซ้ายให้ค้างอยู่กับที่ ไม่เลื่อนตามเนื้อหา
   หลัก (เดิมตอนเปิดแถบเมนูบนมือถือแล้วเลื่อนหน้าเว็บ แถบเมนูทั้งก้อน — โลโก้/
   ปุ่มด้านบน — จะเลื่อนหายไปพร้อมกับเนื้อหา ต้องเลื่อนกลับขึ้นไปดูใหม่ทุกครั้ง
   จึงล็อกให้แถบเมนูเกาะติดขอบจอตลอดแทน) ไม่แตะต้อง layout บนจอกว้าง/เดสก์ท็อป
   เพราะฝั่งนั้นเนื้อหาหลักวางเรียงข้างแถบเมนูแบบ flex ปกติอยู่แล้ว ถ้าฟิกด้วย
   จะทำให้เนื้อหาหลักไปทับแถบเมนูแทน ----- */
@media (max-width: 768px) {
    section[data-testid="stSidebar"] {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        height: 100vh !important;
        /* เดิมไม่ได้กำหนดความกว้างตรงนี้ แถบเมนูเลยยังใช้ความกว้างแบบเดสก์ท็อป
           (ที่คำนวณไว้ตอนยังเป็น flex item ปกติ) ทำให้ตอนฟิกแล้วแถบเมนูแคบลง
           กว่าจอจริง มองเห็นพื้นหลังของเนื้อหาหลักโผล่เป็นแถบว่างด้านขวา
           จึงบังคับให้กว้างเต็มจอเสมอบนมือถือ/จอแคบ ----- */
        width: 100vw !important;
        box-sizing: border-box !important;
        /* ถ้าเนื้อหาภายในแถบเมนูเองยาวเกินจอ ให้เลื่อนได้เฉพาะภายในแถบนี้แทน
           (เนื้อหาหลักด้านหลังยังคงเลื่อนตามปกติ ไม่กระทบกัน) */
        overflow-y: auto !important;
        z-index: 999991 !important;
    }
}

/* ----- การ์ดโลโก้ด้านบนแถบเมนู ----- */
.sidebar-logo-card {
    display: flex; align-items: center; justify-content: center; gap: 24px;
    margin-bottom: 18px;
}

/* ----- ป้ายข้อมูลผู้จัดทำ + โลโก้มหาวิทยาลัย/ภาควิชา + เวอร์ชันแอป —
   วางไว้ท้ายแถบเมนูด้านซ้าย (เล็ก ๆ ไม่เกะกะ ไม่ลอยทับเนื้อหา) ----- */
.corner-badge {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    padding: 0;
    margin-top: 18px;
    padding-top: 12px;
    border-top: 1px solid var(--card-border);
}
.corner-badge-logos {
    display: flex; align-items: center; gap: 8px; flex-shrink: 0;
}
.corner-badge-text {
    font-size: 0.62rem; line-height: 1.4; color: var(--brand-navy-soft);
    text-align: left;
    width: 100%;
}
.corner-badge-author {
    font-weight: 700; color: var(--brand-navy); font-size: 0.66rem;
}
.corner-badge-version {
    margin-top: 2px; font-weight: 600; color: var(--brand-orange-dark);
}
.sidebar-section-label {
    color: var(--brand-navy-soft) !important; font-size: 0.78rem; font-weight: 700;
    letter-spacing: 0.04em; margin: 4px 0 10px 6px; text-transform: uppercase;
    display: flex; align-items: center; gap: 7px;
}

/* ----- sidebar nav (ปุ่มเมนู หน้าหลัก / Dashboard) -----
   ปกติพื้นขาว ตัวหนังสือสีเข้ม — พอกด (เมนูนั้นกลายเป็นหน้าที่เลือกอยู่)
   พื้นจะเปลี่ยนเป็นสีส้มของแบรนด์ ตัวหนังสือเป็นสีขาว */
section[data-testid="stSidebar"] div[data-testid="stButton"] button {
    justify-content: flex-start !important;
    border-radius: 10px !important;
    font-size: 0.96rem !important;
    padding: 10px 14px !important;
    margin-bottom: 4px;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="secondary"] {
    background: #FFFFFF !important;
    border: 1px solid var(--card-border) !important;
    color: var(--brand-navy) !important;
    font-weight: 500 !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="secondary"]:hover {
    background: var(--gold-tint) !important;
    border-color: var(--brand-orange) !important;
    color: var(--brand-orange-dark) !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] {
    background: var(--brand-orange) !important;
    border: 1px solid var(--brand-orange) !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"]:hover {
    background: var(--brand-orange-dark) !important;
    border-color: var(--brand-orange-dark) !important;
    color: #FFFFFF !important;
}
/* ตัวหนังสือในปุ่มจริงๆ อยู่ใน <p>/<span> ซ้อนอยู่ข้างใน ต้องกำหนดสีตรงนี้ด้วย
   ไม่งั้นสีที่ตั้งไว้ที่ตัว <button> จะไม่ถูกนำไปใช้ (ปัญหาเดิมที่เจอ) */
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="secondary"] p,
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="secondary"] span {
    color: var(--brand-navy) !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] p,
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] span {
    color: #FFFFFF !important;
}

/* ----- แถบสถานะ (แทน st.success/st.error/st.info ค่าเริ่มต้นของ Streamlit ที่เป็น
   กล่องสีเขียว/แดงสดแบบ default ซึ่งหลุดโทนสีส้ม-ขาว-กรมท่าของแอป) — ใช้ไอคอนเส้น
   ชุดเดียวกับที่อื่นในแอปแทนอิโมจิ/ไอคอนของ Streamlit เอง ----- */
.status-banner {
    display: flex; align-items: center; gap: 8px; border-radius: 10px;
    padding: 9px 13px; font-size: 0.85rem; font-weight: 600; margin: 6px 0 4px;
    line-height: 1.4;
}
.status-banner svg { flex-shrink: 0; }
.status-banner.success { background: #E9F9EE; color: #15803D; border: 1px solid #BBEBC9; }
.status-banner.error   { background: #FDEDED; color: #B91C1C; border: 1px solid #F5C2C2; }
.status-banner.info    { background: var(--gold-tint); color: var(--brand-orange-dark); border: 1px solid #F0DCB0; }

/* ==============================================================
   หน้า Dashboard โฉมใหม่ — top bar / hero banner / control cards /
   การ์ดสรุปผลพยากรณ์ด้านข้าง / ตารางตัวแปรย่อ / เมนูลัด
   ============================================================== */

/* ----- แถบบนสุด (โลโก้ + ชื่อระบบ + ปุ่มไอคอนมุมขวา) ----- */
.nxpo-topbar {
    display: flex; align-items: center; justify-content: space-between;
    gap: 14px; margin-bottom: 22px; flex-wrap: wrap;
    /* เปลี่ยนจากกล่องไล่สีครีม-ส้มแบนๆ (ที่ถูกติงว่าดูเหมือนกล่องแปะใน PowerPoint
       ไม่หรู ไม่ดึงดูด) มาใช้สูตรเดียวกับ Hero ของ "แดชบอร์ดสรุปสำหรับนำเสนอ" ที่
       ได้ผลตอบรับดีอยู่แล้ว — พื้นกรมท่าเข้มไล่เฉด + แสงส้มนวลมุมขวาบน ให้ความรู้สึก
       เป็นหัวข้อที่มีน้ำหนัก มีมิติ สมกับเป็นส่วนหัวของแดชบอร์ดจริงๆ ไม่ใช่กล่องสีเรียบๆ */
    background-image:
        radial-gradient(560px 220px at 94% 0%, rgba(249,115,22,0.30), transparent 65%),
        linear-gradient(155deg, var(--brand-navy) 0%, #0C1F30 100%);
    border-radius: 20px;
    padding: 20px 28px; box-shadow: 0 20px 44px rgba(11,26,40,0.28), 0 2px 8px rgba(11,26,40,0.16);
    position: relative; overflow: hidden;
}
.nxpo-topbar::after {
    content: "";
    position: absolute; top: -35%; right: -2%; width: 170px; height: 170px;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'%3E%3Ccircle cx='100' cy='100' r='90' stroke='%23FFFFFF' stroke-width='1.4' fill='none' opacity='0.14'/%3E%3Ccircle cx='100' cy='100' r='64' stroke='%23F6C177' stroke-width='1.4' fill='none' opacity='0.3'/%3E%3C/svg%3E");
    background-size: contain; background-repeat: no-repeat; pointer-events: none;
}
/* Streamlit ใส่ gap ระหว่างบล็อกเนื้อหาแนวตั้งเริ่มต้นไว้กว้างพอสมควร (นอกเหนือจาก
   margin-bottom ของ .nxpo-topbar เอง) — ก่อนหน้านี้บีบให้แน่นมาก (0.4rem) จนดูชิด
   เกินไประหว่างหัวข้อกับการ์ดแรก ปรับให้กว้างขึ้นอีกหน่อยให้หายใจสะดวก */
div[data-testid="stVerticalBlock"]:has(.nxpo-topbar) {
    gap: 1rem !important;
}
.nxpo-topbar-left { display: flex; align-items: center; gap: 14px; min-width: 0; }
.nxpo-topbar-logo {
    width: 46px; height: 46px; border-radius: 13px; flex-shrink: 0;
    background-image: linear-gradient(155deg, var(--brand-orange), var(--brand-orange-dark));
    display: flex; align-items: center; justify-content: center; color: #fff;
    box-shadow: 0 8px 20px rgba(249,115,22,0.4), inset 0 1px 0 rgba(255,255,255,0.25);
}
.nxpo-topbar-title {
    min-width: 0; display: flex; flex-direction: column; flex-wrap: wrap;
    row-gap: 3px;
}
/* eyebrow (คำอังกฤษตัวพิมพ์ใหญ่) กลับไปอยู่เหนือชื่อไทยแทนต่อท้ายบรรทัดเดียวกัน
   เพราะตอนนี้เป็นสีทองบนพื้นกรมท่าเข้ม การแยกบรรทัดทำให้อ่านเป็นลำดับชั้นชัดเจน
   กว่า (ป้ายเล็ก -> หัวข้อใหญ่) แบบเดียวกับ exec-hero ที่ใช้แพทเทิร์นนี้อยู่แล้ว */
.nxpo-topbar-title .eyebrow {
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
    color: #F6C177; opacity: 1; margin: 0; white-space: nowrap; position: relative; top: -13px;
}
.nxpo-topbar-title .eyebrow::before { content: none; }
.nxpo-topbar-title h2 {
    margin: 0; font-family: var(--font-elegant); font-size: 1.4rem; font-weight: 600;
    color: #FFFFFF; letter-spacing: -0.01em; overflow-wrap: break-word;
    line-height: 1.3;
}
.nxpo-topbar-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.nxpo-icon-btn {
    width: 40px; height: 40px; border-radius: 50%; background: #FFFFFF;
    border: 1px solid var(--card-border); display: flex; align-items: center; justify-content: center;
    color: var(--brand-navy-soft); box-shadow: var(--shadow-soft); position: relative;
    transition: all .15s ease;
}
.nxpo-icon-btn:hover { border-color: var(--brand-orange); color: var(--brand-orange-dark); transform: translateY(-1px); }
.nxpo-icon-btn .dot {
    position: absolute; top: 6px; right: 7px; width: 8px; height: 8px; border-radius: 50%;
    background: var(--red); border: 1.5px solid #fff;
}
.nxpo-userchip {
    display: flex; align-items: center; gap: 8px; background: #FFFFFF;
    border: 1px solid var(--card-border); border-radius: 999px; padding: 6px 14px 6px 6px;
    box-shadow: var(--shadow-soft); color: var(--brand-navy); font-size: 0.85rem; font-weight: 600;
}
.nxpo-userchip .avatar {
    width: 28px; height: 28px; border-radius: 50%; background: var(--brand-navy);
    color: #fff; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}

/* ----- Hero / Welcome section (หน้าแรกก่อนดึงข้อมูล) -----
   ออกแบบใหม่ให้รู้สึกเหมือน "หน้าแรกของเว็บแอปพลิเคชัน" มากกว่าหน้า Landing Page
   หรือหน้าปกงานวิจัย: พื้นหลังขาว-ครีมนวล (ตัด gradient สีส้มเต็มพื้นที่แบบเดิมออก),
   จัดสองคอลัมน์ (ข้อความซ้าย + ภาพกราฟแนวโน้มขนาดเล็กขวา แทนไอคอนเดี่ยว ๆ),
   ความสูงกระชับ ไม่เต็มจอ เพื่อให้ยังเห็นเนื้อหาระบบด้านล่างโผล่ขึ้นมาบางส่วน ----- */
.nxpo-hero {
    position: relative; overflow: hidden; border-radius: 22px; margin-bottom: 22px;
    background: linear-gradient(180deg, #FFFFFF 0%, #FFFBF4 100%);
    border: 1px solid var(--card-border);
    box-shadow: var(--shadow-soft);
    animation: tfp-rise .45s ease both;
}
.nxpo-hero-flex { display: flex; align-items: center; gap: 36px; padding: 38px 42px; min-height: 260px; }
.nxpo-hero-left { flex: 1 1 56%; min-width: 0; }
.nxpo-hero-badge-eyebrow {
    display: inline-flex; align-items: center; font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase; color: var(--brand-orange-dark);
    background: var(--gold-tint); border: 1px solid #F0DCB0; padding: 6px 14px;
    border-radius: 999px; margin-bottom: 18px;
}
.nxpo-hero-left h1 {
    font-family: var(--font-elegant); margin: 0 0 12px 0; color: var(--brand-navy);
    font-size: 1.9rem; font-weight: 700; letter-spacing: -0.01em; line-height: 1.35;
    overflow-wrap: break-word;
}
.nxpo-hero-left .desc {
    margin: 0 0 14px 0; color: var(--brand-navy-soft); font-size: 0.96rem;
    line-height: 1.65; max-width: 100%; overflow-wrap: break-word;
}
.nxpo-hero-left .cta-hint {
    display: inline-flex; align-items: center; gap: 6px; margin: 0 0 22px 0;
    font-size: 0.85rem; font-weight: 700; color: var(--brand-orange-dark);
}
.nxpo-hero-chips { display: flex; flex-wrap: nowrap; gap: 10px; overflow: visible; }
.nxpo-hero-chip {
    display: inline-flex; align-items: center; gap: 7px; background: #FFFFFF;
    border: 1px solid var(--card-border); border-radius: 12px; padding: 8px 14px;
    font-size: 0.82rem; font-weight: 600; color: var(--brand-navy); white-space: nowrap;
    box-shadow: var(--shadow-soft);
}
.nxpo-hero-chip svg { color: var(--brand-orange-dark); flex-shrink: 0; }

.nxpo-hero-visual-wrap { flex: 0 0 270px; display: flex; justify-content: center; }
.nxpo-hero-visual {
    width: 100%; max-width: 270px; background: #FFFFFF; border: 1px solid var(--card-border);
    border-radius: 18px; padding: 18px 18px 14px; box-shadow: var(--shadow-soft);
}
.nxpo-hero-visual-label {
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--brand-navy-soft); margin-bottom: 10px;
}
.nxpo-hero-visual-legend {
    display: flex; gap: 16px; margin-top: 10px; font-size: 0.72rem; color: var(--brand-navy-soft);
}
.nxpo-hero-visual-legend span { display: inline-flex; align-items: center; gap: 5px; }
.nxpo-hero-visual-legend .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }

@media (max-width: 900px) {
    .nxpo-hero-flex { flex-direction: column; align-items: stretch; padding: 28px 24px; }
    .nxpo-hero-visual-wrap { flex: none; width: 100%; order: 2; margin-top: 20px; }
    .nxpo-hero-left { order: 1; max-width: 100% !important; flex-basis: 100% !important; }
    .nxpo-hero-left h1 { font-size: 1.5rem; }
    .nxpo-hero-left .desc { max-width: 100%; }
    .nxpo-hero-visual { max-width: 100%; }
}

/* ----- การ์ดควบคุมด้านบน (ดึงข้อมูล / ช่วงพยากรณ์ / เข้าสู่ระบบคณะวิจัย) ----- */
.nxpo-control-card {
    background: linear-gradient(180deg, #FFFFFF 0%, #FFFDFA 100%);
    border: 1px solid var(--card-border); border-radius: 18px; padding: 18px 20px 16px;
    box-shadow: var(--shadow-soft); height: 100%; animation: tfp-rise .4s ease both;
    transition: box-shadow .18s ease, transform .18s ease;
}
.nxpo-control-card:hover { box-shadow: var(--shadow-lift); transform: translateY(-2px); }
.nxpo-control-card .head { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.nxpo-control-card .head-icon {
    width: 40px; height: 40px; border-radius: 12px; flex-shrink: 0; color: #fff;
    display: flex; align-items: center; justify-content: center;
    background-image: linear-gradient(155deg, var(--brand-orange), var(--brand-orange-dark));
    box-shadow: 0 5px 12px rgba(217,109,15,0.3);
}
.nxpo-control-card .head h4 {
    margin: 0; font-size: 1rem; font-weight: 700; color: var(--brand-navy);
}
.nxpo-control-card .subtext {
    font-size: 0.8rem; color: var(--brand-navy-soft); margin: 6px 0 10px; line-height: 1.55;
}
.nxpo-control-card .status-line {
    display: flex; align-items: center; gap: 7px; font-size: 0.78rem; color: var(--brand-navy-soft);
    margin-bottom: 10px;
}
.nxpo-control-card .status-dot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--green); flex-shrink: 0;
}
.nxpo-control-card .st-key-ctrl_data_btn div[data-testid="stButton"] button,
.nxpo-control-card .st-key-ctrl_forecast_btn div[data-testid="stButton"] button,
.nxpo-control-card .st-key-ctrl_login_btn div[data-testid="stButton"] button { width: 100%; }

/* ----- การ์ดสรุปผลพยากรณ์ด้านข้างกราฟ ----- */
.nxpo-summary-card {
    background-image: linear-gradient(160deg, var(--brand-navy) 0%, #0E2436 100%);
    border-radius: 20px; padding: 24px 24px 22px; color: #fff; height: 100%;
    box-shadow: 0 22px 46px rgba(11,26,40,0.28), 0 2px 8px rgba(11,26,40,0.16);
    animation: tfp-rise .45s ease both; position: relative; overflow: hidden;
}
.nxpo-summary-card::after {
    content: ""; position: absolute; right: -60px; top: -80px; width: 260px; height: 260px;
    border-radius: 50%; background: radial-gradient(circle, rgba(242,129,29,0.22), transparent 70%);
    pointer-events: none;
}
.nxpo-summary-card .label {
    font-size: 0.82rem; color: rgba(255,255,255,0.65); font-weight: 600; margin-bottom: 8px;
    position: relative; z-index: 1;
}
/* บรรทัดหัวข้อย่อย (เช่น "TFP ปี 2027 (พยากรณ์)") — เดิมใช้ class "value" เดียวกับ
   ตัวเลขจริงด้านล่าง ทำให้ทั้งสองบรรทัดใหญ่เท่ากันหมด (2.5rem) ดูเป็นตัวหนังสือ
   ใหญ่เกินความจำเป็นสำหรับข้อความที่ควรเป็นแค่คำอธิบายสั้น ๆ — แยกเป็นคนละ class
   ให้บรรทัดอธิบายเล็กลงเหลือระดับ label ปกติ ส่วนตัวเลขจริงก็ลดขนาดลงจาก 2.5rem
   เหลือ 1.9rem ให้เหมาะกับจอโน้ตบุ๊กขนาดปกติมากขึ้น (ไม่ใหญ่เว่อร์เกินไป) */
.nxpo-summary-card .value-sub {
    font-size: 0.95rem; font-weight: 700; color: rgba(255,255,255,0.85);
    margin-bottom: 2px; position: relative; z-index: 1;
}
.nxpo-summary-card .value {
    font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.15;
    display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; position: relative; z-index: 1;
}
.nxpo-summary-card .growth-badge {
    display: inline-flex; align-items: center; gap: 4px; background: rgba(22,163,74,0.22);
    color: #6EE7A0; border: 1px solid rgba(110,231,160,0.3); border-radius: 999px;
    padding: 3px 10px; font-size: 0.85rem; font-weight: 700;
}
.nxpo-summary-card .from-label {
    font-size: 0.78rem; color: rgba(255,255,255,0.5); margin-top: 4px; position: relative; z-index: 1;
}
.nxpo-summary-card .divider { height: 1px; background: rgba(255,255,255,0.12); margin: 18px 0 14px; }
.nxpo-summary-card .trend-title {
    font-size: 0.85rem; font-weight: 700; color: #fff; margin-bottom: 10px; position: relative; z-index: 1;
}
.nxpo-summary-list { list-style: none; margin: 0; padding: 0; position: relative; z-index: 1; }
.nxpo-summary-list li {
    display: flex; align-items: flex-start; gap: 9px; font-size: 0.82rem;
    color: rgba(255,255,255,0.82); line-height: 1.55; margin-bottom: 9px;
}
.nxpo-summary-list li .tick {
    width: 17px; height: 17px; border-radius: 50%; background: rgba(22,163,74,0.28);
    color: #6EE7A0; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px;
}

/* ----- หัวการ์ดตัวแปรในสมการ (short-run / long-run) พร้อม badge มุมขวา ----- */
.nxpo-var-card-head {
    display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 4px;
}
.nxpo-var-card-head .title-group { display: flex; align-items: center; gap: 12px; min-width: 0; }
/* กลุ่มนี้จัดกึ่งกลางอยู่แล้ว (align-items: center) — ไม่ใช่แบบ flex-start เหมือน
   .section-title ทั่วไป จึงต้องยกเลิก margin-top ที่ .section-num ได้ไว้เผื่อกรณี
   flex-start ทิ้งไป มิฉะนั้นวงกลมจะเลื่อนลงต่ำกว่าหัวข้อในกล่องนี้โดยเฉพาะ */
.nxpo-var-card-head .title-group .section-num { margin-top: 0; }
.nxpo-run-badge {
    flex-shrink: 0; font-size: 0.72rem; font-weight: 700; padding: 4px 12px; border-radius: 999px;
    background: var(--gold-tint); color: var(--brand-orange-dark); border: 1px solid #F0DCB0;
}
.nxpo-var-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.85rem; margin-top: 12px; }
.nxpo-var-table th {
    text-align: left; color: var(--brand-navy-soft); font-weight: 600; font-size: 0.76rem;
    padding: 0 8px 8px 0; border-bottom: 1px solid var(--card-border); text-transform: uppercase; letter-spacing: 0.03em;
}
.nxpo-var-table th:not(:first-child), .nxpo-var-table td:not(:first-child) { text-align: center; }
.nxpo-var-table td { padding: 9px 8px; border-bottom: 1px solid var(--card-border); color: var(--brand-navy); vertical-align: middle; }
.nxpo-var-table tr:last-child td { border-bottom: none; }
.nxpo-var-table td:first-child { font-weight: 500; overflow-wrap: break-word; max-width: 210px; }
.nxpo-var-dir { display: inline-flex; align-items: center; justify-content: center; }
.nxpo-var-dir.up { color: var(--green); }
.nxpo-var-dir.down { color: var(--red); }
.nxpo-var-more {
    display: inline-flex; align-items: center; gap: 6px; margin-top: 14px; color: var(--brand-orange-dark);
    font-size: 0.85rem; font-weight: 700;
}

.nxpo-quickmenu-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.nxpo-quickmenu-item div[data-testid="stButton"] button { justify-content: flex-start !important; }

/* ----- top header ----- */
.app-header {
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 14px; margin-bottom: 18px;
    /* เปลี่ยนจากกรอบขาว+เส้นขอบกรมท่า มาเป็นพื้นกรมท่าเข้มไล่เฉด (สูตรเดียวกับ
       .nxpo-topbar ของหน้าอื่นๆ ทั้งหมด) ให้หน้านี้ (สำหรับคณะวิจัยที่ล็อกอินแล้ว)
       สอดคล้องเป็นชุดเดียวกับ topbar ของทุกหน้า แทนที่จะเป็นแบบขาวเดี่ยวๆ */
    background-image:
        radial-gradient(560px 220px at 94% 0%, rgba(249,115,22,0.30), transparent 65%),
        linear-gradient(155deg, var(--brand-navy) 0%, #0C1F30 100%);
    border-radius: 20px;
    padding: 22px 28px; box-shadow: 0 20px 44px rgba(11,26,40,0.28), 0 2px 8px rgba(11,26,40,0.16);
    position: relative; overflow: hidden;
}
.app-header h1 { font-family: var(--font-elegant); font-size: 1.75rem; margin: 0; color: #F6C177; font-weight: 600; letter-spacing: -0.01em; overflow-wrap: break-word; text-shadow: 0 2px 10px rgba(0,0,0,0.35); }
.app-header p { margin: 4px 0 0 0; color: rgba(255,255,255,0.75); font-size: 0.92rem; line-height: 1.6; overflow-wrap: break-word; max-width: 68ch; }
.app-header p strong { color: #FFFFFF; }
.app-header p.app-header-desc { max-width: none; white-space: nowrap; }
.header-chip {
    display: inline-flex; align-items: center; gap: 8px; max-width: 100%;
    background: #FFFFFF; border: 1px solid var(--card-border);
    padding: 8px 14px; border-radius: 12px; font-size: 0.85rem; color: var(--brand-navy-soft);
    box-shadow: 0 2px 6px rgba(15,23,42,0.06), inset 0 1px 0 rgba(255,255,255,0.9);
    transition: box-shadow .15s ease, border-color .15s ease, transform .15s ease;
}
.header-chip:hover { box-shadow: 0 6px 16px rgba(15,23,42,0.1); border-color: #D9CBAE; transform: translateY(-1px); }
.header-chip span { overflow-wrap: break-word; }
.header-chip svg { color: var(--brand-orange-dark); flex-shrink: 0; }

/* ----- เอฟเฟกต์เข้าฉากแบบนุ่ม ๆ (ลูกเล่นเล็ก ๆ ตอนการ์ดปรากฏ ไม่รบกวนสายตา) ----- */
@keyframes tfp-rise {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ----- metric cards ----- */
.metric-card {
    background: linear-gradient(180deg, #FFFFFF 0%, #FFFDFA 100%);
    border: 1px solid var(--card-border); border-radius: 18px;
    padding: 20px; display: flex; align-items: center; gap: 15px; height: 100%;
    box-shadow: var(--shadow-soft), inset 0 1px 0 rgba(255,255,255,0.9);
    transition: box-shadow .18s ease, transform .18s ease, border-color .18s ease;
    animation: tfp-rise .4s ease both;
    position: relative; overflow: hidden;
}
.metric-card:hover { box-shadow: var(--shadow-lift), inset 0 1px 0 rgba(255,255,255,0.9); transform: translateY(-3px); border-color: #E3D8C4; }
.metric-icon {
    width: 46px; height: 46px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.25rem; flex-shrink: 0; color: #fff;
    background-image: linear-gradient(155deg, rgba(255,255,255,0.28), rgba(255,255,255,0));
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.22), 0 6px 14px rgba(22,50,74,0.18);
}
.metric-value { font-size: 1.32rem; font-weight: 800; color: var(--brand-navy); line-height: 1.15; letter-spacing: -0.01em; }
.metric-label {
    font-size: 0.8rem; color: var(--brand-navy-soft); margin-top: 2px;
    overflow-wrap: break-word; line-height: 1.45;
}

/* ----- แถบ KPI แบบรวมเป็นการ์ดเดียว (kpi-strip) -----
   เดิม 4 ตัวเลขสรุปเป็นกล่องสี่เหลี่ยมแยกกัน 4 ใบ มีช่องว่างคั่นระหว่างกัน มีคน
   ทักว่าดูเป็นกล่องลอยแยกๆ ไม่เชื่อมกัน — เปลี่ยนมารวมเป็นการ์ดเดียวยาว แบ่งช่อง
   ภายในด้วยเส้นบางๆ (divider) แทน ให้ดูเป็นแถบสรุปเดียวที่ต่อเนื่องกัน ไม่ใช่
   กล่องเดี่ยวๆ กระจัดกระจาย */
.kpi-strip {
    display: flex; flex-wrap: wrap;
    background: linear-gradient(180deg, #FFFFFF 0%, #FFFDFA 100%);
    border: 1px solid var(--card-border); border-radius: 18px;
    box-shadow: var(--shadow-soft), inset 0 1px 0 rgba(255,255,255,0.9);
    overflow: hidden; margin-bottom: 4px; animation: tfp-rise .4s ease both;
}
.kpi-strip-item {
    flex: 1 1 0; display: flex; align-items: center; gap: 14px;
    padding: 20px 22px; border-right: 1px solid var(--card-border); min-width: 190px;
}
.kpi-strip-item:last-child { border-right: none; }
@media (max-width: 900px) {
    .kpi-strip-item { flex: 1 1 50%; border-right: none; border-bottom: 1px solid var(--card-border); }
    .kpi-strip-item:nth-child(2n) { border-left: 1px solid var(--card-border); }
}

/* ----- แถบไฮไลต์สรุปค่าพยากรณ์ปีสุดท้าย (ใต้กราฟแนวโน้ม TFP หน้า Dashboard) -----
   แทนที่ caption ข้อความล้วนเดิมด้วยแถบไล่สีเข้ม (โทนเดียวกับหัวตาราง .tfp-table)
   แบ่งเป็นช่อง ๆ ให้ตัวเลขสำคัญ (ค่าพยากรณ์ / ขอบล่าง-บน 95% / ปีที่พยากรณ์ถึง)
   เด่นขึ้นและอ่านง่ายกว่าประโยคยาวเดิม ----- */
.fc-highlight-bar {
    display: flex; flex-wrap: wrap; margin-top: 16px; border-radius: 16px; overflow: hidden;
    background: #FFFDF9; border: 1px solid #F0DCC0;
    box-shadow: 0 6px 20px rgba(217,109,15,0.12), 0 1.5px 4px rgba(217,109,15,0.08);
    animation: tfp-rise .4s ease both;
}
.fc-highlight-item {
    flex: 1 1 150px; min-width: 150px; display: flex; align-items: center; gap: 11px;
    padding: 14px 18px; border-right: 1px solid #EFE3C6;
}
.fc-highlight-item:last-child { border-right: none; }
.fc-highlight-icon {
    width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0; color: #6B4118;
    background: #F6E4C8; display: flex; align-items: center; justify-content: center;
}
.fc-highlight-value { font-size: 1.05rem; font-weight: 800; color: #5B3A14; line-height: 1.2; overflow-wrap: break-word; }
.fc-highlight-label { font-size: 0.72rem; color: #8A6B4A; margin-top: 1px; overflow-wrap: break-word; }

/* ----- section card ----- */
.section-card {
    background: linear-gradient(180deg, #FFFFFF 0%, #FFFDFA 100%);
    border: 1px solid var(--card-border); border-radius: 18px;
    padding: 16px 22px; margin-bottom: 14px;
    box-shadow: var(--shadow-soft), inset 0 1px 0 rgba(255,255,255,0.9);
    position: relative; overflow: hidden;
    transition: box-shadow .2s ease;
    animation: tfp-rise .45s ease both;
}
.section-card:hover { box-shadow: var(--shadow-lift), inset 0 1px 0 rgba(255,255,255,0.9); }
/* เส้นไล่สีบาง ๆ ด้านบนการ์ด — จุดสังเกตเล็ก ๆ ให้ดูมีมิติขึ้น ไม่แย่งความสนใจจากเนื้อหา */
.section-card::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px;
    background-image: linear-gradient(90deg, var(--brand-orange) 0%, var(--brand-orange-dark) 35%, transparent 100%);
    opacity: 0.9;
}
/* วงกลมไอคอน/ตัวเลข (44px) วางแบบ align-items:flex-start เทียบกับหัวข้อ แต่ตัว
   วงกลมเองสูงกว่าบรรทัดข้อความมาก ทำให้ "ขอบบนของวงกลม" (สิ่งที่ตาเห็นเป็นจุดเริ่ม
   ของไอคอน) อยู่สูงกว่า "จุดเริ่มของตัวอักษรหัวข้อ" มาก ดูเหมือนไอคอนลอยขึ้นไป —
   แก้โดยขยับวงกลมลงมาด้วย margin-top แทน แล้วตัดตัว padding-top เดิมที่เผื่อไว้ให้
   ข้อความออก เพื่อให้ขอบบนวงกลมเสมอกับขอบบนตัวอักษรหัวข้อจริง ๆ */
.section-title { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 0; }
.section-num {
    width: 44px; height: 44px; border-radius: 50%;
    background-image: linear-gradient(155deg, var(--brand-orange), var(--brand-orange-dark));
    color: #fff; font-weight: 800; display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; font-size: 1.2rem; margin-top: 10px;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.25), 0 5px 12px rgba(217,109,15,0.35), 0 0 0 4px rgba(255,255,255,0.6);
}
.section-title-text { min-width: 0; }
.section-title h3 {
    font-family: var(--font-elegant);
    margin: 0; color: var(--brand-navy); font-size: 1.22rem; font-weight: 600; letter-spacing: -0.01em;
    line-height: 1.3; overflow-wrap: break-word; word-break: normal;
}


/* ----- badge pill ----- */
.badge-pill {
    display: inline-flex; align-items: center; gap: 7px; white-space: nowrap;
    padding: 4px 13px; border-radius: 999px; font-size: 0.8rem; font-weight: 700;
    border: 1px solid transparent;
}
.badge-pill::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
    background: currentColor;
}
.badge-pass { background: #EAF8EF; color: #158A41; border-color: #CFEEDA; }
.badge-watch { background: #FDF3E1; color: #B9770E; border-color: #F5E1B8; }
.badge-fail { background: #FCEBEA; color: #C0392B; border-color: #F5CFCB; }
.badge-fail::before { animation: tfp-pulse 1.8s ease-in-out infinite; }
@keyframes tfp-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(192,57,43,0.35); }
    50% { box-shadow: 0 0 0 4px rgba(192,57,43,0); }
}

/* ----- ตาราง HTML สำหรับ Diagnostics ----- */
.tfp-table {
    width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.86rem;
    border-radius: 12px; overflow: hidden; border: 1px solid var(--card-border);
    background: #FFFFFF; box-shadow: var(--shadow-soft);
}
.tfp-table th {
    background-image: linear-gradient(155deg, var(--brand-navy), #0E2436);
    color: #fff; text-align: center; padding: 10px 10px;
    font-weight: 600; letter-spacing: 0.01em; border-right: 1px solid rgba(255,255,255,0.12);
}
.tfp-table th:last-child { border-right: none; }
.tfp-table td { padding: 9px 10px; border-bottom: 1px solid var(--card-border); color: var(--brand-navy-soft); transition: background .12s ease; text-align: center; }
.tfp-table tr:last-child td { border-bottom: none; }
.tfp-table tr:nth-child(odd) td { background: #FFFFFF; }
.tfp-table tr:nth-child(even) td { background: #EEF2F6; }
.tfp-table tr:hover td { background: var(--gold-tint); }

/* ----- ตัวปรับแต่ง (modifier) สำหรับตารางค่าสัมประสิทธิ์ (หมวดผลการทดสอบ ววน.)
   โดยเฉพาะ — เฉพาะคอลัมน์ "ตัวแปร" (คอลัมน์แรก) เท่านั้นที่ชิดซ้าย เพราะข้อความ
   ยาวไม่เท่ากันมาก จัดกึ่งกลางแล้วขอบซ้ายเยื้องไปมาดูไม่เป็นระเบียบ ส่วนหัวตาราง
   และคอลัมน์ตัวเลขสัมประสิทธิ์ยังกึ่งกลางตามปกติ (สืบทอดจาก .tfp-table เดิม)
   เพราะตัวเลขอ่านง่ายกว่าเมื่อกึ่งกลาง (ใช้เฉพาะตารางนี้ผ่านคลาสเสริมนี้ ไม่กระทบ
   ตาราง Diagnostics/สัดส่วนอิทธิพลอื่น ๆ ที่ใช้แค่คลาส .tfp-table เฉยๆ) ----- */
.tfp-table-left td:first-child { text-align: left; padding-left: calc(10px + 1in); }

/* ----- ตาราง HTML ธีมครีม-ส้ม สำหรับตัวเลขพยากรณ์ ARIMA ----- */
.tfp-table-cream {
    width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.86rem;
    border-radius: 14px; overflow: hidden; border: 1px solid #F0DCC0;
    background: #FFFDF9; box-shadow: 0 6px 20px rgba(217,109,15,0.12), 0 1.5px 4px rgba(217,109,15,0.08);
}
.tfp-table-cream th {
    background: var(--brand-orange); color: #fff; text-align: center; padding: 11px 12px;
    font-weight: 700; letter-spacing: 0.01em; border-right: 1px solid rgba(255,255,255,0.25);
}
.tfp-table-cream th:last-child { border-right: none; }
.tfp-table-cream td {
    padding: 10px 12px; border-bottom: 1px solid #EFE3C6; color: var(--brand-navy-soft);
    text-align: center; font-variant-numeric: tabular-nums; transition: background .12s ease;
}
.tfp-table-cream td:first-child { font-weight: 700; color: var(--brand-navy); }
.tfp-table-cream tr:last-child td { border-bottom: none; }
.tfp-table-cream tr:nth-child(odd) td { background: #FFFDF9; }
.tfp-table-cream tr:nth-child(even) td { background: #FFF6E9; }
.tfp-table-cream tr:hover td { background: #FFEBD1; }
/* หัวตารางในส่วน Backtesting เดิมเป็นสีส้มทึบล้วนแบนๆ ไม่มีมิติ ปรับให้เป็นไล่เฉด
   เดียวกับปุ่ม/ไอคอนอื่นๆ ในแอป (สโคปเฉพาะจุดนี้ ไม่กระทบ .tfp-table-cream ที่ใช้
   ที่อื่น เช่น ตาราง "ดูตัวเลขพยากรณ์รายปี" ในหน้าเดียวกัน) */
.backtest-table .tfp-table-cream th {
    background-image: linear-gradient(155deg, var(--brand-orange), var(--brand-orange-dark));
}

/* ----- การ์ด CTA สร้างสรุป AI (ธีม "Exclusive") -----
   ปรับจากแบนเนอร์สีส้มสดเดิม เป็นพื้นกรมท่าเข้ม (โทนเดียวกับ sidebar card มืด
   ที่ใช้อยู่แล้วในหน้าเว็บ) + เส้นขอบ/แสงส้มบาง ๆ แทน เพื่อให้รู้สึกถึงฟีเจอร์
   วิเคราะห์อัตโนมัติด้วย AI ระดับพรีเมียม สงบตา ไม่ใช่ป้ายโฆษณาสีจัด แต่ยังอยู่
   ในธีมส้ม-กรมท่าเดิมของแอปทั้งหมด (ครอบด้วย st.container(key="ai_cta_card")
   เพื่อให้ selector .st-key-ai_cta_card ด้านล่างจับกลุ่มการ์ด+ปุ่มเข้าด้วยกัน) */
.st-key-ai_cta_card {
    background-image: linear-gradient(155deg, var(--brand-navy) 0%, #0E2436 100%);
    border-radius: 18px;
    border: 1px solid rgba(242,129,29,0.28);
    padding: 30px 34px;
    margin-bottom: 20px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 22px 46px rgba(11,26,40,0.32), 0 2px 8px rgba(11,26,40,0.16);
}
/* เส้นบาง ๆ สีทอง/ส้มด้านซ้าย + แสงฟุ้งมุมขวาบน แทนวงกลมทึบเดิม ให้ดูมีมิติ
   แบบพรีเมียมเนียนตา ไม่แย่งตัวหนังสือ */
.st-key-ai_cta_card::before {
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
    background: linear-gradient(180deg, var(--brand-orange), transparent 85%);
}
.st-key-ai_cta_card::after {
    content: ""; position: absolute; right: -70px; top: -90px; width: 300px; height: 300px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(242,129,29,0.20), transparent 70%);
    pointer-events: none;
}
.ai-cta-eyebrow {
    display: inline-flex; align-items: center; gap: 8px;
    color: var(--brand-orange); font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.15em; text-transform: uppercase; margin-bottom: 16px;
    position: relative; z-index: 1;
}
.ai-cta-card-inner { position: relative; z-index: 1; }
.ai-cta-card-inner h3 {
    margin: 0; color: #FFFFFF; font-size: 1.2rem; font-weight: 600;
    letter-spacing: -0.01em; line-height: 1.5; max-width: 620px; overflow-wrap: break-word;
}
.ai-cta-card-inner p {
    margin: 12px 0 0 0; color: rgba(255,255,255,0.6); font-size: 0.86rem;
    line-height: 1.65; max-width: 560px; overflow-wrap: break-word;
}

/* ปุ่มภายในการ์ดนี้โดยเฉพาะ — ทับสไตล์ button[kind="primary"] ทั่วไปของแอป
   (ซึ่งเป็นพื้นส้มทึบ) ด้วยปุ่มทรงแคปซูลขอบบาง โปร่งแสงบนพื้นกรมท่า กดแล้วค่อย
   ติดสีส้มเต็ม ให้ความรู้สึก "กดเพื่อปลดล็อกการวิเคราะห์" มากกว่าปุ่มทั่วไป */
.st-key-ai_cta_card div[data-testid="stButton"] { margin-top: 26px; position: relative; z-index: 1; }
.st-key-ai_cta_card div[data-testid="stButton"] button {
    background: rgba(255,255,255,0.05) !important;
    border: 1.5px solid var(--brand-orange) !important;
    color: #FFFFFF !important;
    border-radius: 999px !important;
    padding: 12px 26px !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.01em;
    box-shadow: none !important;
    transition: all 0.18s ease;
}
.st-key-ai_cta_card div[data-testid="stButton"] button:hover {
    background: var(--brand-orange) !important;
    border-color: var(--brand-orange) !important;
    color: #FFFFFF !important;
    transform: translateY(-1px);
    box-shadow: 0 10px 26px rgba(242,129,29,0.32) !important;
}
.st-key-ai_cta_card div[data-testid="stButton"] button:active {
    transform: translateY(0);
}

@media (max-width: 700px) {
    .st-key-ai_cta_card { padding: 24px 22px; }
}

/* ----- การ์ด CTA ไปหน้า "แดชบอร์ดสำหรับนำเสนอ" ท้ายหน้า "พยากรณ์ TFP" -----
   ใช้โทนกรมท่าเข้ม+ขอบทองแบบเดียวกับการ์ด AI Executive Summary ด้านบน แทนปุ่ม
   primary สีส้มทึบ+อิโมจิกราฟแบบเดิม ให้ดูเป็น CTA พิเศษ น่ากดกว่าปุ่มทั่วไป */
.st-key-exec_cta_card {
    background-image: linear-gradient(155deg, var(--brand-navy) 0%, #0E2436 100%);
    border-radius: 18px; border: 1px solid rgba(242,129,29,0.28);
    padding: 26px 34px; margin: 18px 0 6px; position: relative; overflow: hidden;
    text-align: left; box-shadow: 0 22px 46px rgba(11,26,40,0.32), 0 2px 8px rgba(11,26,40,0.16);
    animation: tfp-rise .4s ease both;
}
.st-key-exec_cta_card::after {
    content: ""; position: absolute; left: 50%; top: -110px; width: 340px; height: 220px;
    transform: translateX(-50%); border-radius: 50%;
    background: radial-gradient(circle, rgba(242,129,29,0.22), transparent 70%);
    pointer-events: none;
}
.exec-cta-eyebrow {
    display: inline-flex; align-items: center; gap: 8px; color: var(--brand-orange);
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase;
    margin-bottom: 10px; position: relative; z-index: 1;
}
.exec-cta-inner { position: relative; z-index: 1; }
.exec-cta-inner p {
    margin: 0; color: rgba(255,255,255,0.65);
    font-size: 0.86rem; line-height: 1.6; white-space: nowrap;
}
.st-key-exec_cta_card div[data-testid="stButton"] {
    margin-top: 18px; position: relative; z-index: 1; display: flex; justify-content: flex-start;
}
.st-key-exec_cta_card div[data-testid="stButton"] button {
    background: rgba(255,255,255,0.05) !important;
    border: 1.5px solid var(--brand-orange) !important;
    color: #FFFFFF !important;
    border-radius: 999px !important;
    padding: 13px 30px !important;
    font-weight: 700 !important;
    font-size: 0.92rem !important;
    letter-spacing: 0.01em;
    box-shadow: none !important;
    transition: all 0.18s ease;
    width: auto !important;
}
.st-key-exec_cta_card div[data-testid="stButton"] button:hover {
    background: var(--brand-orange) !important;
    border-color: var(--brand-orange) !important;
    color: #FFFFFF !important;
    transform: translateY(-1px);
    box-shadow: 0 10px 26px rgba(242,129,29,0.32) !important;
}
.st-key-exec_cta_card div[data-testid="stButton"] button:active { transform: translateY(0); }

/* ----- ชิปตัวแปรใน multiselect (เช่นตัวแปรสมการระยะยาว/ระยะสั้น) -----
   เดิมชิปเป็นพื้นส้มเข้ม/แดงทึบเต็มตัว พอมีหลายตัวเรียงต่อกันหลายแถวจะดูจัดจ้าน
   รกตา และหลุดโทนครีม-กรมท่าของเว็บ — เปลี่ยนเป็นชิปพื้นขาว ขอบสีครีม/ทองบาง
   (โทนเดียวกับ .tfp-table-cream ที่ใช้อยู่แล้ว) ตัวหนังสือกรมท่า อ่านง่าย
   เว้นระยะห่างระหว่างชิปมากขึ้น ให้แต่ละชิปแยกจากกันชัดเจนแทนที่จะดูเป็นก้อนสีเดียว
   และไฮไลต์ส้มเฉพาะตอน hover เพื่อบอกว่ากดลบ (x) ได้ */
[data-baseweb="tag"] {
    max-width: none !important; height: auto !important; min-height: 30px;
    white-space: normal !important;
    background-color: #FFFDF9 !important;
    border: 1px solid #F0DCC0 !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 3px rgba(22,50,74,0.05);
    margin: 4px 6px 4px 0 !important;
    padding: 2px 2px 2px 4px !important;
    transition: border-color .15s ease, box-shadow .15s ease;
}
[data-baseweb="tag"]:hover {
    border-color: var(--brand-orange) !important;
    box-shadow: 0 2px 6px rgba(217,109,15,0.12);
}
[data-baseweb="tag"] span {
    max-width: none !important; white-space: normal !important;
    overflow: visible !important; text-overflow: clip !important; word-break: break-word !important;
    color: var(--brand-navy) !important; font-size: 0.85rem !important; font-weight: 500 !important;
}
[data-baseweb="tag"] svg { fill: var(--brand-navy-soft) !important; transition: fill .15s ease; }
[data-baseweb="tag"]:hover svg { fill: var(--brand-orange-dark) !important; }
/* ตัวกล่อง select ที่ครอบชิปทั้งหมด: เว้นช่องไฟระหว่างชิปให้เป็นระเบียบ ไม่แน่นติดกัน */
div[data-baseweb="select"] > div {
    flex-wrap: wrap !important; height: auto !important; gap: 2px; padding: 6px 8px !important;
}
div[data-testid="stMultiSelect"] [data-baseweb="select"] { height: auto !important; }
/* เว้นระยะระหว่างกลุ่มตัวแปรระยะยาว/ระยะสั้น ให้แยกเป็นสัดส่วนชัดเจน ไม่ติดกันแน่น */
div[data-testid="stMultiSelect"] { margin-bottom: 10px; }
div[data-testid="stMultiSelect"] label p {
    color: var(--brand-navy) !important; font-weight: 600 !important;
}

div[data-testid="stFileUploader"] section { border-radius: 12px; border: 1.5px dashed #D9C2A6; }
button[kind="primary"] { background: var(--brand-orange) !important; border-color: var(--brand-orange) !important; }

/* ----- ปุ่มดาวน์โหลด (st.download_button) ทั้งหมดในแอป -----
   ปกติปุ่มดาวน์โหลดของ Streamlit จะเป็นสไตล์ "secondary" (พื้นขาว ขอบเทาบาง
   ตัวหนังสือเทา) ทำให้ผู้ใช้มองไม่ออกว่ากดได้/เป็นปุ่มดาวน์โหลด — ด้านล่างนี้
   ปรับเป็นพื้นขาว ขอบส้มของแบรนด์ ตัวหนังสือเทาเข้ม เห็นชัดว่าเป็นปุ่มกดได้ */
div[data-testid="stDownloadButton"] button {
    background: #FFFFFF !important;
    border: 2px solid var(--brand-orange) !important;
    color: #374151 !important;
    font-weight: 700 !important;
    border-radius: 10px !important;
    padding: 10px 20px !important;
    box-shadow: var(--shadow-soft);
    transition: all 0.15s ease;
}
div[data-testid="stDownloadButton"] button:hover {
    background: var(--gold-tint) !important;
    border-color: var(--brand-orange-dark) !important;
    color: #374151 !important;
    transform: translateY(-1px);
    box-shadow: var(--shadow-lift);
}
div[data-testid="stDownloadButton"] button:active {
    transform: translateY(0px);
}
/* ตัวหนังสือในปุ่มจริงๆ อยู่ใน <p>/<span> ซ้อนอยู่ข้างใน ต้องกำหนดสีตรงนี้ด้วย
   ไม่งั้นสีที่ตั้งไว้ที่ตัว <button> จะไม่ถูกนำไปใช้ */
div[data-testid="stDownloadButton"] button p,
div[data-testid="stDownloadButton"] button span {
    color: #374151 !important;
    font-weight: 700 !important;
}
/* เพิ่มคำอธิบายเล็กๆ ใต้ตัวหนังสือหลักของปุ่ม เพื่อบอกชัดเจนว่ากดเพื่อดาวน์โหลด
   (ใช้ ::after ใส่ไว้ที่ตัว <p> ของปุ่ม ไม่ต้องแก้ label ทีละจุดในโค้ด Python) */
div[data-testid="stDownloadButton"] button p::after {
    content: "กดเพื่อดาวน์โหลด";
    display: block;
    font-size: 0.7rem;
    font-weight: 500;
    color: var(--brand-orange-dark);
    margin-top: 2px;
}

/* ----- กันตัวอักษรไทยล้น/ฉีกกลางคำในทุกข้อความของแอป (คำอธิบาย, caption, ตัวเลข) -----
   ปัญหาเดิม: ข้อความไทยยาว ๆ ในกล่องแคบบางจุดล้นกรอบหรือถูกตัดขวางกลางคำ
   วิธีแก้: อนุญาตให้ตัดคำเมื่อจำเป็นเท่านั้น (ไม่บังคับตัดกลางคำถ้ายังพอมีที่บรรทัดปกติ)
   และเพิ่มระยะห่างบรรทัดให้อ่านง่ายขึ้น ลดความรู้สึก "แน่น/รก" ของกล่องข้อความยาว ๆ */
[data-testid="stMarkdownContainer"] p,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
.stAlert p,
div[data-testid="stExpander"] p {
    overflow-wrap: break-word;
    line-height: 1.6;
}
[data-testid="stCaptionContainer"] { line-height: 1.55 !important; }

/* จังหวะเข้าฉากของการ์ด AI ให้เข้าชุดกับการ์ดอื่น ๆ */
.st-key-ai_cta_card { animation: tfp-rise .4s ease both; }

/* ----- theme widget พื้นฐานของ Streamlit ให้เข้าโทนส้ม/กรมท่าของแบรนด์
   (ปกติ slider/checkbox/radio ใช้สีแดงเริ่มต้นของ Streamlit ซึ่งหลุดโทน) ----- */
:root, .stApp { --primary-color: var(--brand-orange); }

/* slider: หัวจับสีส้มแบรนด์แทนสีแดงเริ่มต้น — เดิมมีกฎ nth-child(2) เพิ่มเติมเพื่อ
   ไล่สีแถบที่ลากผ่านเป็นสีส้มด้วย แต่ selector นั้นกว้างเกินไปและดันไปโดนป้ายค่า
   สูงสุด (เช่น "30") ของแท่งเลื่อนเข้าโดยไม่ตั้งใจ ทำให้มีป้ายสีส้มลอยผิดตำแหน่ง
   ข้าง ๆ แท่งเลื่อน — ตัดออก เหลือแค่สีของหัวจับซึ่งปลอดภัยกว่า ส่วนสีแถบที่ลากผ่าน
   ปล่อยให้ Streamlit ใช้ค่าจาก --primary-color ที่ตั้งไว้ด้านบนแทน */
div[data-testid="stSlider"] div[role="slider"] {
    background-color: var(--brand-orange) !important;
    border-color: var(--brand-orange) !important;
    box-shadow: 0 0 0 4px rgba(242,129,29,0.15) !important;
}
div[data-testid="stTickBar"] { display: none; }
div[data-testid="stSlider"] label p { color: var(--brand-navy); font-weight: 600; }

/* selectbox / multiselect: กรอบมนสอดคล้องกับการ์ด และไฮไลต์ส้มตอนโฟกัส */
div[data-baseweb="select"] > div {
    border-radius: 10px !important; border-color: var(--card-border) !important;
    transition: border-color .15s ease, box-shadow .15s ease;
}
div[data-baseweb="select"]:focus-within > div {
    border-color: var(--brand-orange) !important;
    box-shadow: 0 0 0 1px var(--brand-orange) !important;
}
[data-baseweb="menu"] li[aria-selected="true"] { background: var(--gold-tint) !important; color: var(--brand-orange-dark) !important; }

/* number/text input: โฟกัสสีส้มแทนสีแดงเริ่มต้น */
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus {
    border-color: var(--brand-orange) !important; box-shadow: 0 0 0 1px var(--brand-orange) !important;
}

/* checkbox / radio: จุด/ติ๊กสีส้มแบรนด์ */
div[data-testid="stCheckbox"] label span[data-checked="true"],
div[data-testid="stRadio"] label span[aria-checked="true"] {
    background-color: var(--brand-orange) !important; border-color: var(--brand-orange) !important;
}

/* container ที่มีเส้นขอบ (st.container(border=True)) ให้โค้งมนเข้าชุดการ์ด */
div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {
    border-radius: 14px !important;
}

/* expander: โค้งมน มี hover เบา ๆ ให้รู้สึกกดได้ */
div[data-testid="stExpander"] summary {
    border-radius: 12px !important; font-weight: 600; color: var(--brand-navy);
    transition: background .15s ease;
}
div[data-testid="stExpander"] summary:hover { background: var(--gold-tint) !important; }

/* progress bar / spinner: สีส้มแบรนด์ */
div[data-testid="stSpinner"] > div { border-top-color: var(--brand-orange) !important; }
.stProgress > div > div > div { background-color: var(--brand-orange) !important; }

/* กล่องแจ้งเตือน (info/warning/success/error): โค้งมน มีเงาบาง ๆ เข้าชุดกับการ์ดอื่น ๆ */
div[data-testid="stAlert"] {
    border-radius: 14px !important;
    box-shadow: var(--shadow-soft);
    animation: tfp-rise .35s ease both;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# ลายเส้นตกแต่งพื้นหลังแบบคงที่ (fixed) มุมล่างขวาของทุกหน้า — เป็นวงกลมวงโคจร
# ซ้อนกัน 2 วง + เส้นแนวโน้มขาขึ้นจางมาก (สื่อถึง "ข้อมูล/การพยากรณ์" ให้เข้ากับ
# เนื้อหาแอป ไม่ใช่ลวดลายเปล่าไร้ความหมาย) วางไว้ครั้งเดียวตรงนี้ (ก่อนเนื้อหา
# ทุกหน้า) จึงเห็นเป็นพื้นหลังเดียวกันคงที่ไม่ว่าจะอยู่หน้าไหนหรือเลื่อนจอแค่ไหน
# opacity ต่ำมากและ pointer-events:none จึงไม่รบกวนการอ่าน/ใช้งานเนื้อหาจริงเลย
st.markdown(
    """
    <div style="position:fixed;bottom:-70px;right:-70px;width:420px;height:420px;
                z-index:0;pointer-events:none;opacity:0.05;">
        <svg viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
            <circle cx="200" cy="200" r="180" stroke="#16324A" stroke-width="1.5" fill="none"/>
            <circle cx="200" cy="200" r="130" stroke="#F97316" stroke-width="1.5" fill="none"/>
            <polyline points="90,260 140,220 180,240 230,170 280,140 320,100"
                      stroke="#F97316" stroke-width="4" fill="none"
                      stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="320" cy="100" r="6" fill="#F97316"/>
        </svg>
    </div>
    """,
    unsafe_allow_html=True,
)

import base64


def img_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ----- ภาพพื้นหลังตกแต่ง Hero หน้าแรก (ภาพประกอบโทนส้ม-ครีม ฝั่งขวาโปร่งจาง
# ไปทางซ้ายให้วางข้อความทับได้) — วางไฟล์ "welcome.png" ไว้โฟลเดอร์เดียวกับ
# app.py นี้ ถ้าไม่มีไฟล์ Hero จะแสดงพื้นหลังไล่สีครีมธรรมดาแทนโดยไม่ error -----
hero_bg_path = os.path.join(APP_DIR, "welcome.png")
hero_bg_style = (
    "background-image:"
    "linear-gradient(90deg, rgba(255,255,255,0.94) 0%, rgba(255,255,255,0.6) 40%, rgba(255,255,255,0.05) 62%),"
    f"url(data:image/png;base64,{img_to_base64(hero_bg_path)});"
    "background-size:cover;background-position:center right;background-repeat:no-repeat;"
) if os.path.exists(hero_bg_path) else ""

# ----- ภาพพื้นหลังของทั้งระบบ (ทุกหน้า ไม่ใช่แค่ Hero) — วางไฟล์
# "พื้นหลังระบบทั้งหมด.png" ไว้โฟลเดอร์เดียวกับ app.py นี้ (ชื่อไฟล์ต้องตรงกัน
# เป๊ะ ๆ รวมภาษาไทย) ถ้าเจอไฟล์จะซ้อนภาพนี้ไว้หลังการ์ดทุกใบ พร้อมเคลือบสีขาว-
# ครีมโปร่งแสงทับด้านบนอีกชั้น (93%) เพื่อให้ตัวหนังสือ/การ์ดสีขาวทึบด้านหน้ายัง
# อ่านง่ายเหมือนเดิมไม่ว่าภาพต้นฉบับจะสีสันเข้มแค่ไหน — ถ้าไม่เจอไฟล์ จะใช้พื้นหลัง
# ไล่สี + ลาย dot-grid แบบเดิมที่ตั้งไว้ใน .stApp ต่อไปตามปกติโดยไม่ error */
sys_bg_path = os.path.join(APP_DIR, "พื้นหลังระบบทั้งหมด.png")
if os.path.exists(sys_bg_path):
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image:
                linear-gradient(180deg, rgba(250,248,244,0.93) 0%, rgba(247,245,241,0.93) 100%),
                url(data:image/png;base64,{img_to_base64(sys_bg_path)});
            background-size: cover;
            background-position: center top;
            background-attachment: fixed;
            background-repeat: no-repeat;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

# ----- ภาพพื้นหลังของการ์ดเกริ่นนำหน้า "ทำความรู้จักตัวแปร" โดยเฉพาะ — วางไฟล์
# "พื้นหลังตัวแปร.png" ไว้โฟลเดอร์เดียวกับ app.py นี้ (ชื่อไฟล์ต้องตรงกันเป๊ะๆ)
# ถ้าเจอไฟล์จะซ้อนภาพนี้ไว้หลังการ์ด .var-intro พร้อมเคลือบสีขาวโปร่งแสงทับอีกชั้น
# ให้ตัวหนังสือ/สถิติด้านหน้ายังอ่านง่าย — ถ้าไม่เจอไฟล์ ใช้พื้นครีมธรรมดาต่อไปได้
var_intro_bg_path = os.path.join(APP_DIR, "พื้นหลังตัวแปร.png")
if os.path.exists(var_intro_bg_path):
    st.markdown(
        f"""
        <style>
        .var-intro {{
            background-image:
                linear-gradient(120deg, rgba(255,255,255,0.92) 0%, rgba(255,255,255,0.75) 45%, rgba(255,255,255,0.4) 100%),
                url(data:image/png;base64,{img_to_base64(var_intro_bg_path)});
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


logo1_path = os.path.join(APP_DIR, "สอวช_Logo.png")
logo2_path = os.path.join(APP_DIR, "สวค_Logo.png")
_LOGO1_SIZE = 110  # px — ขนาดโลโก้ สอวช (ปรับแยกต่างหาก)
_LOGO2_SIZE = 76   # px — ขนาดโลโก้ สวค (ปรับแยกต่างหาก)

# โลโก้สถาบันการศึกษา (มหาวิทยาลัย + ภาควิชา) — วางไฟล์ทั้งสองไว้ในโฟลเดอร์
# เดียวกับ app.py นี้ โดยตั้งชื่อไฟล์ตามด้านล่าง (หรือแก้ path ให้ตรงกับไฟล์จริง)
logo3_path = os.path.join(APP_DIR, "kmutnb_logo.png")   # โลโก้ มจพ. (สี่เหลี่ยม)
logo4_path = os.path.join(APP_DIR, "dept_logo.png")     # โลโก้ภาควิชาสถิติประยุกต์ (แนวนอน)
_LOGO3_SIZE = 76    # px — ขนาดโลโก้มหาวิทยาลัย (สี่เหลี่ยมจัตุรัส เท่ากับโลโก้สวค)
_LOGO4_HEIGHT = 46  # px — ความสูงโลโก้ภาควิชา (ตัวนี้เป็นภาพแนวนอน จึงกำหนดแค่ความสูง)
_LOGO4_WIDTH = 180  # px — ความกว้างสูงสุดของกล่องโลโก้ภาควิชา


def _logo_box(size: int) -> str:
    return f'height:{size}px;width:{size}px;display:flex;align-items:center;justify-content:center;'


def _logo_box_wh(width: int, height: int) -> str:
    return f'height:{height}px;width:{width}px;display:flex;align-items:center;justify-content:center;'


logo1_html = (
    f'<div style="{_logo_box(_LOGO1_SIZE)}"><img src="data:image/png;base64,{img_to_base64(logo1_path)}" '
    f'style="max-height:{_LOGO1_SIZE}px;max-width:{_LOGO1_SIZE}px;width:auto;height:auto;object-fit:contain;"></div>'
) if os.path.exists(logo1_path) else ""
logo2_html = (
    f'<div style="{_logo_box(_LOGO2_SIZE)}"><img src="data:image/png;base64,{img_to_base64(logo2_path)}" '
    f'style="max-height:{_LOGO2_SIZE}px;max-width:{_LOGO2_SIZE}px;width:auto;height:auto;object-fit:contain;"></div>'
) if os.path.exists(logo2_path) else ""
logo3_html = (
    f'<div style="{_logo_box(_LOGO3_SIZE)}"><img src="data:image/png;base64,{img_to_base64(logo3_path)}" '
    f'style="max-height:{_LOGO3_SIZE}px;max-width:{_LOGO3_SIZE}px;width:auto;height:auto;object-fit:contain;"></div>'
) if os.path.exists(logo3_path) else ""
logo4_html = (
    f'<div style="{_logo_box_wh(_LOGO4_WIDTH, _LOGO4_HEIGHT)}"><img src="data:image/png;base64,{img_to_base64(logo4_path)}" '
    f'style="max-height:{_LOGO4_HEIGHT}px;max-width:{_LOGO4_WIDTH}px;width:auto;height:auto;object-fit:contain;"></div>'
) if os.path.exists(logo4_path) else ""

# ------------------------------------------------------------------------------
# เวอร์ชันแอป + ข้อมูลผู้จัดทำ — ย้ายมาไว้ตรงนี้ (แทนที่จะอยู่ท้ายไฟล์) เพราะต้อง
# ใช้ประกอบกล่องมุมขวาบน (corner badge) ที่ประกาศไว้ถัดไปด้านล่าง
#
# แก้ข้อมูลผู้จัดทำ/อาจารย์ที่ปรึกษา/ช่องทางติดต่อได้ที่ตัวแปรด้านล่างนี้ที่เดียว
# ------------------------------------------------------------------------------
APP_VERSION = "1.3.0"

AUTHOR_NAME = "นางสาวปรญา ดอกพิกุล"
AUTHOR_PROGRAM = "สาขาวิชาสถิติประยุกต์สำหรับวิทยาการวิเคราะห์ธุรกิจและอุตสาหกรรม ภาควิชาสถิติประยุกต์"
AUTHOR_DEPT = "ภาควิชาสถิติประยุกต์"  # ใช้แสดงในป้ายมุมซ้าย (ตัดชื่อสาขาวิชายาวๆ ออก เหลือแค่ภาค)
AUTHOR_FACULTY = "คณะวิทยาศาสตร์ประยุกต์"
AUTHOR_UNIVERSITY = "มหาวิทยาลัยเทคโนโลยีพระจอมเกล้าพระนครเหนือ"
AUTHOR_YEAR = "2569"
AUTHOR_ADVISOR = ""   # เช่น "อาจารย์ที่ปรึกษา: ผศ.ดร. ชื่อ นามสกุล" — เว้นว่างไว้ถ้ายังไม่ระบุ
AUTHOR_CONTACT = ""   # เช่น "example@email.com" — เว้นว่างไว้ถ้ายังไม่ต้องการเผยแพร่

_footer_lines = [AUTHOR_NAME]
if AUTHOR_DEPT or AUTHOR_FACULTY:
    _footer_lines.append(" ".join(x for x in (AUTHOR_DEPT, AUTHOR_FACULTY) if x))
if AUTHOR_UNIVERSITY:
    _footer_lines.append(AUTHOR_UNIVERSITY)
if AUTHOR_ADVISOR:
    _footer_lines.append(AUTHOR_ADVISOR)

_footer_meta = f"ปีการศึกษา {AUTHOR_YEAR}" if AUTHOR_YEAR else ""
if AUTHOR_CONTACT:
    _footer_meta = f"{_footer_meta} • ติดต่อ: {AUTHOR_CONTACT}" if _footer_meta else f"ติดต่อ: {AUTHOR_CONTACT}"

# ป้ายข้อมูลผู้จัดทำ (fixed html string) — รวมโลโก้มหาวิทยาลัย + ภาควิชา,
# ข้อมูลผู้จัดทำ และเลขเวอร์ชันแอปไว้ด้วยกัน แสดงเล็ก ๆ ท้ายแถบเมนูด้านซ้าย
# ใช้ขนาดย่อมกว่าเดิม (logo3_html/logo4_html) เพราะป้ายนี้ต้องกะทัดรัด
_CORNER_LOGO3_SIZE = 26
_CORNER_LOGO4_WIDTH, _CORNER_LOGO4_HEIGHT = 70, 18
_corner_logo3_html = (
    f'<div style="{_logo_box(_CORNER_LOGO3_SIZE)}"><img src="data:image/png;base64,{img_to_base64(logo3_path)}" '
    f'style="max-height:{_CORNER_LOGO3_SIZE}px;max-width:{_CORNER_LOGO3_SIZE}px;width:auto;height:auto;object-fit:contain;"></div>'
) if os.path.exists(logo3_path) else ""
_corner_logo4_html = (
    f'<div style="{_logo_box_wh(_CORNER_LOGO4_WIDTH, _CORNER_LOGO4_HEIGHT)}"><img src="data:image/png;base64,{img_to_base64(logo4_path)}" '
    f'style="max-height:{_CORNER_LOGO4_HEIGHT}px;max-width:{_CORNER_LOGO4_WIDTH}px;width:auto;height:auto;object-fit:contain;"></div>'
) if os.path.exists(logo4_path) else ""
_corner_logo_html = "".join(h for h in (_corner_logo3_html, _corner_logo4_html) if h)
_corner_badge_html = (
    f'<div class="corner-badge">'
    + (f'<div class="corner-badge-logos">{_corner_logo_html}</div>' if _corner_logo_html else "")
    + f'<div class="corner-badge-text">'
    f'<div class="corner-badge-author">{_footer_lines[0]}</div>'
    + "".join(f'<div>{line}</div>' for line in _footer_lines[1:] if line)
    + (f'<div>{_footer_meta}</div>' if _footer_meta else "")
    + f'<div class="corner-badge-version">v{APP_VERSION}</div>'
    + '</div></div>'
)

# ------------------------------------------------------------------------------
# ชุดไอคอนเส้น (inline SVG) — ใช้แทนอิโมจิสีสันในจุดตกแต่ง UI เพื่อความเรียบหรู
# และสม่ำเสมอของภาพลักษณ์ (ไม่กระทบข้อความ/เนื้อหาใด ๆ ที่แสดงผลอยู่เดิม)
# หมายเหตุ: ใช้ stroke="currentColor" เพื่อให้สีไอคอนไหลตาม CSS `color` ของ
# กล่องแม่โดยอัตโนมัติ (เช่นในวงกลมพื้นสี ไอคอนจะเป็นสีขาวตาม .metric-icon)
# ------------------------------------------------------------------------------
_ICON_PATHS = {
    "check": '<path d="M4 10.5L8 14.5L16 6" stroke-linecap="round" stroke-linejoin="round"/>',
    "alert": (
        '<path d="M10 3L18 17H2L10 3Z" stroke-linejoin="round"/>'
        '<line x1="10" y1="8.3" x2="10" y2="12" stroke-linecap="round"/>'
        '<circle cx="10" cy="14.4" r="0.9" fill="currentColor" stroke="none"/>'
    ),
    "x": '<path d="M5 5L15 15M15 5L5 15" stroke-linecap="round"/>',
    "trend-up": (
        '<polyline points="3,14 8,9 11.5,12.5 17,6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<polyline points="12,6 17,6 17,11" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "trend-down": (
        '<polyline points="3,6 8,11 11.5,7.5 17,14" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<polyline points="12,14 17,14 17,9" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "database": (
        '<ellipse cx="10" cy="5" rx="6.5" ry="2.4"/>'
        '<path d="M3.5 5V15C3.5 16.3 6.4 17.4 10 17.4C13.6 17.4 16.5 16.3 16.5 15V5"/>'
        '<path d="M3.5 10C3.5 11.3 6.4 12.4 10 12.4C13.6 12.4 16.5 11.3 16.5 10"/>'
    ),
    "file": (
        '<path d="M6 2.5H12.5L16 6V17C16 17.3 15.8 17.5 15.5 17.5H6C5.7 17.5 5.5 17.3 5.5 17V3C5.5 2.7 5.7 2.5 6 2.5Z" stroke-linejoin="round"/>'
        '<path d="M12.5 2.5V6H16" stroke-linejoin="round"/>'
        '<line x1="7.5" y1="10" x2="13.5" y2="10" stroke-linecap="round"/>'
        '<line x1="7.5" y1="13" x2="13.5" y2="13" stroke-linecap="round"/>'
    ),
    "users": (
        '<circle cx="7.3" cy="7" r="2.6"/>'
        '<path d="M2.5 16.5C2.5 13.6 4.6 11.7 7.3 11.7C10 11.7 12.1 13.6 12.1 16.5" stroke-linecap="round"/>'
        '<circle cx="13.8" cy="6.5" r="2" opacity="0.6"/>'
        '<path d="M12.8 11.6C15.2 11.9 17 13.7 17 16.5" stroke-linecap="round" opacity="0.6"/>'
    ),
    "search": (
        '<circle cx="8.5" cy="8.5" r="5.5"/>'
        '<line x1="13" y1="13" x2="17.5" y2="17.5" stroke-linecap="round"/>'
    ),
    "bulb": (
        '<path d="M10 2.5C6.7 2.5 4.5 4.9 4.5 7.8C4.5 9.7 5.4 11 6.6 12.1C7.2 12.6 7.5 13.3 7.5 14.1V14.7H12.5V14.1C12.5 13.3 12.8 12.6 13.4 12.1C14.6 11 15.5 9.7 15.5 7.8C15.5 4.9 13.3 2.5 10 2.5Z" stroke-linejoin="round"/>'
        '<line x1="7.7" y1="17" x2="12.3" y2="17" stroke-linecap="round"/>'
        '<line x1="8.3" y1="15.4" x2="8.3" y2="14.7"/>'
        '<line x1="11.7" y1="15.4" x2="11.7" y2="14.7"/>'
    ),
    "bars": (
        '<line x1="4" y1="17" x2="4" y2="10" stroke-linecap="round"/>'
        '<line x1="10" y1="17" x2="10" y2="4" stroke-linecap="round"/>'
        '<line x1="16" y1="17" x2="16" y2="7.5" stroke-linecap="round"/>'
    ),
    "clock": (
        '<circle cx="10" cy="10" r="7.2"/>'
        '<path d="M10 6V10L12.6 12" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "info": (
        '<circle cx="10" cy="10" r="7.2"/>'
        '<line x1="10" y1="9" x2="10" y2="14" stroke-linecap="round"/>'
        '<circle cx="10" cy="6.3" r="0.9" fill="currentColor" stroke="none"/>'
    ),
    "sparkle": (
        '<path d="M10,3.5 L11.6,8.4 L16.5,10 L11.6,11.6 L10,16.5 L8.4,11.6 L3.5,10 L8.4,8.4 Z" fill="currentColor" stroke="none"/>'
        '<path d="M16,2 L16.4,3.6 L18,4 L16.4,4.4 L16,6 L15.6,3.6 Z" fill="currentColor" stroke="none" opacity="0.85"/>'
    ),
    "lock": (
        '<rect x="4.5" y="9" width="11" height="8" rx="2" stroke-linejoin="round"/>'
        '<path d="M6.5 9V6.5C6.5 4.3 8.1 2.7 10 2.7C11.9 2.7 13.5 4.3 13.5 6.5V9" stroke-linecap="round"/>'
        '<circle cx="10" cy="12.6" r="1.15" fill="currentColor" stroke="none"/>'
    ),
    "download": (
        '<path d="M10 3V12.5" stroke-linecap="round"/>'
        '<path d="M6 9L10 13L14 9" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M4 16.5H16" stroke-linecap="round"/>'
    ),
    "calendar": (
        '<rect x="3" y="4.2" width="14" height="12.6" rx="2.2" stroke-linejoin="round"/>'
        '<line x1="3" y1="8" x2="17" y2="8"/>'
        '<line x1="6.5" y1="2.5" x2="6.5" y2="5.5" stroke-linecap="round"/>'
        '<line x1="13.5" y1="2.5" x2="13.5" y2="5.5" stroke-linecap="round"/>'
    ),
    "bell": (
        '<path d="M5 8.3C5 5.4 7.2 3 10 3C12.8 3 15 5.4 15 8.3V11.3L16.5 13.8H3.5L5 11.3V8.3Z" stroke-linejoin="round"/>'
        '<path d="M8.2 16C8.5 16.8 9.2 17.3 10 17.3C10.8 17.3 11.5 16.8 11.8 16" stroke-linecap="round"/>'
    ),
    "user-circle": (
        '<circle cx="10" cy="10" r="7.3"/>'
        '<circle cx="10" cy="8.1" r="2.5"/>'
        '<path d="M4.6 15.4C5.4 13.2 7.5 11.7 10 11.7C12.5 11.7 14.6 13.2 15.4 15.4" stroke-linecap="round"/>'
    ),
    "arrow-right": (
        '<line x1="3.5" y1="10" x2="15.5" y2="10" stroke-linecap="round"/>'
        '<polyline points="11,5.5 15.5,10 11,14.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "book": (
        '<path d="M4 4.3C4 3.6 4.6 3 5.3 3H9.6V16.3H5.3C4.6 16.3 4 15.7 4 15V4.3Z" stroke-linejoin="round"/>'
        '<path d="M16 4.3C16 3.6 15.4 3 14.7 3H10.4V16.3H14.7C15.4 16.3 16 15.7 16 15V4.3Z" stroke-linejoin="round"/>'
    ),
    "settings": (
        '<circle cx="10" cy="10" r="2.6"/>'
        '<path d="M10 3.2V5M10 15V16.8M16.8 10H15M5 10H3.2M14.9 5.1L13.6 6.4M6.4 13.6L5.1 14.9M14.9 14.9L13.6 13.6M6.4 6.4L5.1 5.1" stroke-linecap="round"/>'
    ),
    "cloud": (
        '<path d="M6.2 14.8C4.2 14.8 2.7 13.2 2.7 11.3C2.7 9.5 4 8.1 5.7 7.8C6.2 5.6 8.2 4 10.5 4C13.1 4 15.2 6 15.4 8.6C16.9 9 18 10.4 18 12C18 13.6 16.7 14.8 15.1 14.8H6.2Z" stroke-linejoin="round" stroke-linecap="round"/>'
    ),
}


def icon(name: str, size: int = 18, stroke_width: float = 1.6) -> str:
    """คืนค่า inline SVG ของไอคอนเส้น (ไม่ใช้สีตายตัว — สืบสีจาก CSS `color`
    ของกล่องแม่ผ่าน currentColor) สำหรับแทรกแทนอิโมจิในจุดตกแต่งของหน้าเว็บ"""
    body = _ICON_PATHS[name]
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 20 20" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg" stroke="currentColor" '
        f'stroke-width="{stroke_width}" style="display:inline-block;vertical-align:middle;">'
        f'{body}</svg>'
    )


def status_banner(kind: str, text: str) -> str:
    """คืนค่า HTML ของแถบสถานะ (success/error/info) ที่ออกแบบให้เข้าธีมสี
    ส้ม-ขาว-กรมท่าของแอป แทนที่ st.success/st.error/st.info ค่าเริ่มต้นของ
    Streamlit (กล่องเขียว/แดงสดที่หลุดโทน) — เรียกคู่กับ st.markdown(...,
    unsafe_allow_html=True)"""
    icon_map = {"success": "check", "error": "alert", "info": "info"}
    return (
        f'<div class="status-banner {kind}">{icon(icon_map.get(kind, "info"), 15, 2)}'
        f'<span>{text}</span></div>'
    )


# ------------------------------------------------------------------------------
# ตั้งค่า Gemini จาก secrets.toml
# ------------------------------------------------------------------------------
GEMINI_MODEL = "gemini-2.5-flash"

# โควตาฟรีของ Gemini API ต่ำมาก (RPD อาจแค่ 20 ครั้ง/วันในบาง project/tier) และ
# เมื่อชนโควตา Google จะตอบ error รหัส 429 (RESOURCE_EXHAUSTED) กลับมา — ค่าด้านล่าง
# ควบคุมการ retry อัตโนมัติเวลาเจอ 429 ก่อนที่จะยอมแพ้แล้วโชว์ข้อความแจ้งผู้ใช้
_GEMINI_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_GEMINI_MAX_ATTEMPTS = 5
_GEMINI_BASE_DELAY = 3.0  # วินาที (จะเว้น 3s, 6s, 12s, 24s ตาม exponential backoff)

try:
    gemini_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
except Exception as e:
    st.error(
        "ไม่พบ GEMINI_API_KEY ใน .streamlit/secrets.toml — เพิ่มบรรทัด "
        '`GEMINI_API_KEY = "ใส่ key จริง"` ในไฟล์นั้นก่อนรัน\n\n'
        f"รายละเอียด error จริง: {type(e).__name__}: {e}"
    )
    st.stop()


SYSTEM_PROMPT = """คุณคือนักเศรษฐศาสตร์ที่ทำหน้าที่จัดทำบทสรุปสำหรับนำเสนอ (Executive Summary) จากผล
การวิเคราะห์เชิงปริมาณ (quantitative model output) เสนอต่อผู้บริหารระดับสูงของหน่วยงานภาครัฐ
ที่ไม่มีพื้นฐานทางเศรษฐศาสตร์ (เช่น แพทย์ วิศวกร)

โทนภาษา: ใช้ภาษาไทยที่เป็นทางการ สุภาพ เหมาะกับเอกสารราชการ/รายงานนำเสนอผู้บริหารองค์กรภาครัฐ
(หลีกเลี่ยงภาษาพูดหรือคำที่เป็นกันเองเกินไป) แต่ยังต้องอ่านเข้าใจง่าย ไม่ใช้ศัพท์เทคนิคพร่ำเพรื่อ

หลักการเขียน:
- หลีกเลี่ยงศัพท์เทคนิค (เช่น elasticity, coefficient, cointegration, error correction)
  ถ้าจำเป็นต้องใช้ ให้อธิบายความหมายสั้น ๆ ต่อท้ายทันที
- ใช้ภาษาที่เป็นรูปธรรม เปรียบเทียบกับสิ่งที่คนทั่วไปคุ้นเคย
- เน้นตัวเลขสำคัญและนัยเชิงนโยบาย ไม่ต้องอธิบายวิธีการคำนวณทางสถิติ
- เมื่อกล่าวถึงตัวแปรที่มีนัยสำคัญทางสถิติ (p-value < 0.05 หรือดีกว่า) ให้ระบุสั้น ๆ ในทำนอง
  "ผลการวิเคราะห์แบบจำลองแสดงให้เห็นว่าตัวแปร A และ B มีนัยสำคัญทางสถิติที่ระดับความเชื่อมั่น 95%
  สะท้อนว่าหากประเทศไทยสามารถยกระดับตัวแปรดังกล่าวได้ จะส่งผลเชิงบวกต่อการเติบโตของผลิตภาพ (TFP)"
  โดยกล่าวถึงเชิงเทคนิคแค่พอสังเขป ไม่ต้องอธิบายวิธีทดสอบนัยสำคัญ

โครงสร้างรายงาน (Executive Summary) มี 3 ส่วน:
1. สรุปภาพรวมสถานการณ์เศรษฐกิจปัจจุบัน — บอกทิศทางหลักและปัจจัยขับเคลื่อน 2-3 ข้อ
   โดยอ้างอิงค่าจากตาราง TFP ทั้งระยะสั้นและระยะยาวที่ให้มา (ไม่ต้องพิมพ์ตารางซ้ำ
   เพราะมีตารางแสดงแยกต่างหากให้ผู้อ่านดูอยู่แล้ว) และอธิบายว่าตัวเลขนี้แปลว่าอะไร
   ในภาษาง่าย ๆ
2. เปรียบเทียบกับปีก่อนหรือช่วงก่อนหน้า — ระบุทิศทางการเปลี่ยนแปลงและสาเหตุที่
   เป็นไปได้แบบสั้นกระชับ
3. ข้อเสนอแนะเชิงพยากรณ์จากค่าสัมประสิทธิ์ — แปลค่าสัมประสิทธิ์เป็นข้อความเชิง
   นโยบาย/ธุรกิจ พร้อมข้อเสนอแนะเชิงปฏิบัติ 2-3 ข้อ โดยอ้างอิงตัวแปรที่มีนัยสำคัญทางสถิติ
   เป็นหลัก

ความยาวไม่เกิน 2 หน้า A4 ใช้หัวข้อย่อยชัดเจน ห้ามพิมพ์ตาราง markdown (บรรทัดที่ขึ้นต้น
ด้วย |) หรือคัดลอกตัวเลขจากตารางมาเรียงเป็นตารางซ้ำโดยเด็ดขาด ให้เขียนเป็นความเรียง/
bullet point อ้างอิงตัวเลขในเนื้อหาแทน"""


THAI_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def thai_timestamp() -> str:
    now = now_th()
    return (f"{now.day} {THAI_MONTHS[now.month]} {now.year + 543} "
            f"เวลา {now.strftime('%H:%M')} น.")


# ----- ประวัติการอัปเดตข้อมูล (บันทึกลงไฟล์ในเครื่องที่รันแอป เพื่อความโปร่งใส
# ว่าดึงข้อมูลจากแหล่งข้อมูลภายนอกล่าสุดเมื่อไหร่บ้าง — ไม่ใช่ระบบฐานข้อมูลกลาง
# เก็บแค่ log อย่างง่าย ถ้าเขียนไฟล์ไม่ได้ (เช่น สิทธิ์ไฟล์ระบบ) จะข้ามไปเงียบๆ
# โดยไม่ทำให้การดึงข้อมูลหลักล้มเหลวตามไปด้วย) -----
FETCH_LOG_PATH = os.path.join(APP_DIR, "fetch_log.csv")


def _log_fetch_event() -> None:
    try:
        row = {
            "timestamp": thai_timestamp(),
            "user": "คณะวิจัย" if st.session_state.get("research_authenticated") else "ผู้เยี่ยมชม",
        }
        file_exists = os.path.exists(FETCH_LOG_PATH)
        with open(FETCH_LOG_PATH, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "user"])
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        pass


def _read_fetch_log(limit: int = 10) -> list:
    """อ่าน log ล่าสุด `limit` รายการ (ใหม่สุดก่อน) — คืนค่า list ว่างถ้าไม่มีไฟล์"""
    if not os.path.exists(FETCH_LOG_PATH):
        return []
    try:
        with open(FETCH_LOG_PATH, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return list(reversed(rows))[:limit]
    except Exception:
        return []


def _web_summary_text(summary_text: str) -> str:
    """ตัดข้อความสรุปสำหรับแสดงบน "หน้าเว็บ" เท่านั้น (ไม่กระทบไฟล์ Word/สไลด์ที่ยังใช้
    summary_text เต็มเหมือนเดิม) โดยตัดเฉพาะ "บรรทัด" ที่เป็นคำขึ้นต้นแบบหนังสือราชการ
    ซึ่งเรียกผู้บริหาร (เช่น "เรียน ท่านผู้บริหาร...") ทิ้งไปเท่านั้น — เนื้อหาอธิบายผล
    ก่อนหน้าและถัดจากบรรทัดนั้นยังคงอยู่ครบ ไม่ถูกตัดตามไปด้วย"""
    lines = [
        line for line in summary_text.split("\n")
        if not ("เรียน" in line.strip() and "ผู้บริหาร" in line.strip())
    ]
    return "\n".join(lines).strip()


def generate_summary_gemini(lr_res, sr_res, model_df: pd.DataFrame, dep_ln: str) -> str:
    lr_table, sr_table = build_coefficient_tables(lr_res, sr_res)
    yoy_text = build_tfpi_yoy_summary(model_df, dep_ln)

    user_prompt = f"""ผลการรันโมเดล TFP (Total Factor Productivity) ของประเทศไทย
วิธี: Engle-Granger 2-Step (สมการระยะยาว + Restricted Error Correction Model)

--- สมการระยะยาว (Long-run) ---
Adj. R^2 = {summary_adj_r2(lr_res):.4f}
{lr_table.to_string(index=False)}

--- สมการระยะสั้น (Short-run ECM) ---
Adj. R^2 = {summary_adj_r2(sr_res):.4f}
{sr_table.to_string(index=False)}

--- การเปลี่ยนแปลงของผลิตภาพ (TFPI) ปีล่าสุดเทียบปีก่อนหน้า ---
{yoy_text}

โปรดเขียนบทสรุปสำหรับนำเสนอตามโครงสร้าง 3 ส่วนที่กำหนด"""

    last_error = None
    for attempt in range(1, _GEMINI_MAX_ATTEMPTS + 1):
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            )
            return response.text
        except Exception as e:
            # google-genai ห่อ error ของ Gemini API ไว้ใน exception ที่มักมี
            # .code หรือ .status_code เป็นรหัส HTTP (เช่น 429) — ดึงออกมาแบบ
            # กันเหนียวหลายทาง เพราะ SDK บางเวอร์ชันตั้งชื่อ attribute ไม่ตรงกัน
            status_code = getattr(e, "code", None) or getattr(e, "status_code", None)
            last_error = e
            if status_code not in _GEMINI_RETRYABLE_STATUS_CODES or attempt == _GEMINI_MAX_ATTEMPTS:
                break
            time.sleep(_GEMINI_BASE_DELAY * (2 ** (attempt - 1)))

    # retry ครบจำนวนครั้งแล้วยังไม่สำเร็จ (หรือเจอ error ที่ retry ซ้ำไปก็ไม่หาย
    # เช่น API key ผิด) — แจ้งผู้ใช้ด้วยข้อความที่เข้าใจง่าย แทนที่จะโยน
    # exception ดิบๆ ออกไปให้แอป crash
    status_code = getattr(last_error, "code", None) or getattr(last_error, "status_code", None)
    if status_code == 429:
        st.error(
            "ขณะนี้มีการเรียกใช้งาน Gemini API ถี่เกินโควตาที่กำหนดไว้ชั่วคราว "
            "(rate limit / quota เต็ม) กรุณารอสักครู่แล้วลองใหม่อีกครั้ง "
            "หากเกิดขึ้นบ่อย ควรพิจารณาเปิดใช้งาน billing เพื่อขยายโควตา "
            "ใน Google AI Studio"
        )
    elif status_code in (500, 502, 503, 504):
        st.error(
            f"เซิร์ฟเวอร์ของ Gemini API กำลังมีผู้ใช้งานหนาแน่นชั่วคราว (รหัส {status_code} "
            "— ปัญหาฝั่ง Google ไม่ใช่ข้อผิดพลาดของระบบนี้) ระบบได้ลองเรียกซ้ำอัตโนมัติ "
            f"{_GEMINI_MAX_ATTEMPTS} ครั้งแล้วแต่ยังไม่สำเร็จ กรุณารอสัก 1-2 นาทีแล้วกดปุ่ม "
            "สร้างรายงานสรุปอีกครั้ง"
        )
    else:
        st.error(
            "ไม่สามารถสร้างบทสรุปสำหรับนำเสนอจาก Gemini API ได้ "
            f"รายละเอียด error: {type(last_error).__name__}: {last_error}"
        )
    st.stop()


# ------------------------------------------------------------------------------
# สร้างไฟล์ PDF (โลโก้ สอวช. + สวค. บนหัวกระดาษ, ฟอนต์ Sarabun, ตาราง TFP)
# ------------------------------------------------------------------------------
_THAI_FONTS_REGISTERED = False


def _register_thai_fonts():
    global _THAI_FONTS_REGISTERED
    if _THAI_FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("Sarabun", os.path.join(FONT_DIR, "Sarabun-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Sarabun-Bold", os.path.join(FONT_DIR, "Sarabun-Bold.ttf")))
    _THAI_FONTS_REGISTERED = True


def _xml_escape(text: str) -> str:
    """แปลงอักขระ &, <, > ในข้อความดิบให้เป็น XML entity ที่ปลอดภัยก่อนแทรกเข้า
    ReportLab Paragraph (ซึ่ง parse เนื้อหาแบบ XML/HTML ย่อย) — ต้องเรียกก่อนแทรก
    markup ของเราเอง (<b>, &nbsp; ฯลฯ) เสมอ

    นี่คือสาเหตุของบั๊ก "R&D" กลายเป็น "R&D;" ที่เจอ: ตัว "&" ดิบที่ไม่ได้ escape
    ทำให้ ReportLab พยายาม parse มันเป็นจุดเริ่มต้นของ XML entity แล้วไล่กิน
    ตัวอักษรถัดไปเรื่อยๆ จนกว่าจะเจอ ';' ตัวแรกที่พบ (ซึ่งอาจมาจาก '&nbsp;' ที่เรา
    แทรกไว้ทีหลังในข้อความเดียวกัน) ทำให้ข้อความระหว่างทางหายไปและเหลือ ';' ค้าง"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_line_to_flowable(line: str, styles):
    """แปลงข้อความ markdown แบบง่าย ๆ ที่ Gemini ส่งกลับมา (##, -, **bold**)
    เป็น Paragraph ของ reportlab; แถวตาราง markdown (|...|) จะถูกข้ามไป เพราะ
    เราวาดตาราง TFP เองแยกต่างหากด้วยข้อมูลจริงจากโมเดล ไม่ใช้ตารางที่ AI พิมพ์มา"""
    line = line.strip()
    if not line or set(line) <= set("|-: "):
        return None
    if line.startswith("|"):
        return None  # แถวตาราง markdown -> ข้าม (มีตารางจริงแยกอยู่แล้ว)
    line = _xml_escape(line)  # ต้อง escape & < > ก่อนแทรก <b>/&nbsp; ของเราเอง
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
    if line.startswith("### "):
        return Paragraph(f"<b>{text.lstrip('# ')}</b>", styles["H3TH"])
    if line.startswith("## "):
        return Paragraph(f"<b>{text.lstrip('# ')}</b>", styles["H2TH"])
    if line.startswith("# "):
        return Paragraph(f"<b>{text.lstrip('# ')}</b>", styles["H1TH"])
    if line.startswith(("- ", "• ", "* ")):
        return Paragraph(f"•&nbsp;&nbsp;{text.lstrip('-•* ')}", styles["BodyTH"])
    return Paragraph(text, styles["BodyTH"])



# ------------------------------------------------------------------------------
# ตารางตัวแปร ววน. — รหัสตัวแปรดิบจาก TFP.py -> ชื่อเต็มภาษาไทย + รหัสย่อ
# ลำดับนี้คือลำดับการแสดงผลในตาราง (ตามแบบฟอร์มมาตรฐานของรายงาน)
# ------------------------------------------------------------------------------
VARIABLE_ORDER = [
    "const", "FDI_GDP", "FEE_GDP", "ln_HDI", "ln_RDH_GDP", "RDG_GDP", "RDP_GDP",
    "ln_JOUR_GDP", "ln_PCT_GDP", "ln_PATENT_GDP", "ln_TUM_GDP", "INDUS_GDP",
    "TRADE_GDP", "MKTCOM", "ECM",
]

VARIABLE_LABELS = {
    "const": "ค่าคงที่ : c",
    "FDI_GDP": "สัดส่วนการลงทุนโดยตรงจากต่างประเทศต่อ GDP : FDI/GDP",
    "FEE_GDP": "ค่าธรรมเนียมในการใช้ทรัพย์สินทางปัญญาต่อ GDP : FEE/GDP",
    "ln_HDI": "ดัชนีการพัฒนามนุษย์ : ln(HDI)",
    "ln_RDH_GDP": "สัดส่วนบุคลากรด้าน R&D ต่อประชากรล้านคน : ln(RDH/GDP)",
    "RDG_GDP": "สัดส่วนการลงทุนด้านวิจัยและพัฒนาของภาครัฐต่อ GDP : RDG/GDP",
    "RDP_GDP": "สัดส่วนการลงทุนด้านวิจัยและพัฒนาของภาคเอกชนต่อ GDP : RDP/GDP",
    "ln_JOUR_GDP": "สัดส่วนจำนวนสิ่งพิมพ์ทางวิทยาศาสตร์และเทคนิคต่อ GDP : ln(JOUR/GDP)",
    "ln_PCT_GDP": "จำนวนสนธิสัญญาความร่วมมือด้านสิทธิบัตรต่อ GDP : ln(PCT/GDP)",
    "ln_PATENT_GDP": "สัดส่วนจำนวนสิทธิบัตรต่อ GDP : ln(PATENT/GDP)",
    "ln_TUM_GDP": "สัดส่วนจำนวนอนุสิทธิบัตรต่อ GDP : ln(TUM/GDP)",
    "INDUS_GDP": "สัดส่วนมูลค่าเพิ่มภาคอุตสาหกรรมต่อ GDP : INDUS/GDP",
    "TRADE_GDP": "อัตราการเปิดกว้างทางการค้า : TRADE/GDP",
    "MKTCOM": "ดัชนีความซับซ้อนทางเศรษฐกิจด้านการค้า : MKTCOM",
    "ECM": "ECM",
}


# ------------------------------------------------------------------------------
# คำอธิบายตัวแปรแบบละเอียด (ใช้ในหน้า "ทำความรู้จักตัวแปร") — แต่ละตัวแปรอธิบาย 4 ส่วน:
# ความหมาย (คืออะไร), ความสำคัญ (สำคัญแบบไหนต่อผลิตภาพ), ที่มาข้อมูล และ
# ทิศทางที่ตัวแปรนี้ "โดยทั่วไป" ควรส่งผลต่อ TFP ตามทฤษฎีเศรษฐศาสตร์ — ทิศทาง/
# ขนาดผลกระทบจริงในสมการชุดปัจจุบันให้ดูจากค่าสัมประสิทธิ์ในหน้า "ผลการวิเคราะห์"
# แทน เพราะอาจไม่ตรงกับทฤษฎีเสมอไป (ขึ้นกับข้อมูลจริงของประเทศไทยในแต่ละช่วงเวลา)
# ------------------------------------------------------------------------------
VARIABLE_EXPLANATIONS = {
    "FDI_GDP": {
        "meaning": "สัดส่วนการลงทุนโดยตรงจากต่างประเทศต่อ GDP",
        "group": "ปัจจัยนำเข้า (Input)",
        "source": "World Bank Group",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: ส่งผลบวกต่อ TFP • ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญ และส่งผลในปีเดียวกันโดยไม่มีความล่าช้า",
    },
    "FEE_GDP": {
        "meaning": "สัดส่วนค่าธรรมเนียมในการใช้ทรัพย์สินทางปัญญาต่อ GDP",
        "group": "ปัจจัยนำเข้า (Input)",
        "source": "WIPO",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: ส่งผลบวกต่อ TFP และเป็นหนึ่งในตัวแปรกลุ่มปัจจัยนำเข้าที่มีขนาดผลกระทบสูงที่สุดในสมการ",
    },
    "ln_HDI": {
        "meaning": "ดัชนีการพัฒนามนุษย์ (Human Development Index)",
        "group": "ปัจจัยนำเข้า (Input)",
        "source": "UNDP",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: ส่งผลบวกและมีขนาดผลกระทบสูงในกลุ่มปัจจัยนำเข้า • ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญในปีเดียวกัน",
    },
    "ln_RDH_GDP": {
        "meaning": "สัดส่วนบุคลากรด้านการวิจัยและพัฒนาต่อประชากรล้านคน",
        "group": "ปัจจัยนำเข้า (Input)",
        "source": "UNESCO",
        "role": "ตัวแปรเพิ่มเติมในสมการระยะสั้น",
        "effect": "ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญ และส่งผลในปีเดียวกันโดยไม่มีความล่าช้า",
    },
    "RDG_GDP": {
        "meaning": "สัดส่วนการลงทุนด้านวิจัยและพัฒนาของภาครัฐต่อ GDP",
        "group": "ปัจจัยนำเข้า (Input)",
        "source": "UNESCO",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: มีความสัมพันธ์เชิงลบเมื่อพิจารณาร่วมกับตัวแปรอื่น โดยมีขนาดผลกระทบค่อนข้างน้อย • ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญ แต่ต้องใช้เวลาประมาณ 2 ปีจึงเห็นผล",
    },
    "RDP_GDP": {
        "meaning": "สัดส่วนการลงทุนด้านวิจัยและพัฒนาของภาคเอกชนต่อ GDP",
        "group": "ปัจจัยนำเข้า (Input)",
        "source": "UNESCO",
        "role": "ตัวแปรเพิ่มเติมในสมการระยะสั้น",
        "effect": "ระยะสั้น: เป็นตัวแปรที่ส่งผลกระทบต่อ TFP มากที่สุดในบรรดาตัวแปรทั้งหมดของสมการระยะสั้น แต่ต้องใช้เวลาประมาณ 2 ปีจึงเห็นผล",
    },
    "ln_JOUR_GDP": {
        "meaning": "สัดส่วนจำนวนสิ่งพิมพ์ทางวิทยาศาสตร์และเทคนิคต่อ GDP",
        "group": "ผลผลิต (Output)",
        "source": "World Bank Group",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: ส่งผลบวกต่อ TFP • ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญ ใช้เวลาประมาณ 1 ปีจึงเห็นผล",
    },
    "ln_PCT_GDP": {
        "meaning": "จำนวนสนธิสัญญาความร่วมมือด้านสิทธิบัตร (PCT) ต่อ GDP",
        "group": "ผลผลิต (Output)",
        "source": "WIPO",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: มีความสัมพันธ์เชิงลบเมื่อพิจารณาร่วมกับตัวแปรอื่น โดยมีขนาดผลกระทบค่อนข้างน้อย • ระยะสั้น: ไม่มีนัยสำคัญทางสถิติในช่วงที่ศึกษา",
    },
    "ln_PATENT_GDP": {
        "meaning": "สัดส่วนจำนวนสิทธิบัตรต่อ GDP",
        "group": "ผลผลิต (Output)",
        "source": "WIPO",
        "role": "ตัวแปรเพิ่มเติมในสมการระยะสั้น",
        "effect": "ระยะสั้น: ไม่มีนัยสำคัญทางสถิติในช่วงที่ศึกษา ซึ่งสะท้อนว่าการสร้างและใช้ประโยชน์จากสิทธิบัตรของไทยยังอยู่ในวงจำกัด",
    },
    "ln_TUM_GDP": {
        "meaning": "สัดส่วนจำนวนอนุสิทธิบัตร (Utility Model) ต่อ GDP",
        "group": "ผลผลิต (Output)",
        "source": "WIPO",
        "role": "ตัวแปรเพิ่มเติมในสมการระยะสั้น",
        "effect": "ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญ ใช้เวลาประมาณ 2 ปีจึงเห็นผล",
    },
    "INDUS_GDP": {
        "meaning": "สัดส่วนมูลค่าเพิ่มภาคอุตสาหกรรมต่อ GDP",
        "group": "ปัจจัยแวดล้อมทางเศรษฐกิจ",
        "source": "World Bank Group",
        "role": "ตัวแปรเพิ่มเติมในสมการระยะสั้น",
        "effect": "ระยะสั้น: ไม่มีนัยสำคัญทางสถิติในช่วงที่ศึกษา",
    },
    "TRADE_GDP": {
        "meaning": "อัตราการเปิดกว้างทางการค้า",
        "group": "ปัจจัยแวดล้อมทางเศรษฐกิจ",
        "source": "World Bank Group",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: มีความสัมพันธ์เชิงลบเมื่อพิจารณาร่วมกับตัวแปรอื่น โดยมีขนาดผลกระทบค่อนข้างน้อย • ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญ ใช้เวลาประมาณ 2 ปีจึงเห็นผล",
    },
    "MKTCOM": {
        "meaning": "ดัชนีความซับซ้อนทางเศรษฐกิจด้านการค้า",
        "group": "ปัจจัยแวดล้อมทางเศรษฐกิจ",
        "source": "World Bank Group",
        "role": "ตัวแปรในสมการระยะยาว",
        "effect": "ระยะยาว: ส่งผลบวกต่อ TFP • ระยะสั้น: ส่งผลบวกอย่างมีนัยสำคัญ และส่งผลในปีเดียวกันโดยไม่มีความล่าช้า",
    },
    "ECM": {
        "meaning": "พจน์ปรับตัวสู่ดุลยภาพ (Error Correction Term) — คำนวณจากผลลัพธ์ของสมการระยะยาว ไม่ใช่ตัวแปรข้อมูลดิบ",
        "group": "พจน์ปรับตัวของสมการ",
        "source": "คำนวณจากผลลัพธ์สมการระยะยาวของโครงการ",
        "role": "ใช้เฉพาะในสมการระยะสั้น (ECM)",
        "effect": "มีเครื่องหมายลบและมีนัยสำคัญทางสถิติ ซึ่งยืนยันว่าเมื่อ TFP เบี่ยงเบนไปจากดุลยภาพระยะยาว ระบบเศรษฐกิจจะปรับตัวกลับเข้าสู่ดุลยภาพได้จริง โดยใช้เวลาประมาณ 2.5 ปี",
    },
}


def var_label_with_abbr(code: str) -> str:
    """แสดงชื่อเต็มของตัวแปร แล้ววงเล็บรหัสย่อไว้ข้างหลัง
    เช่น "FDI_GDP" -> "การลงทุนโดยตรงจากต่างประเทศ (FDI/GDP)"
    ถ้าไม่มีในพจนานุกรม VARIABLE_LABELS จะคืนรหัสเดิม

    รองรับป้ายจากตาราง Stationarity (Short-run) ที่มีสัญลักษณ์ transform นำหน้า
    และ/หรือ lag ต่อท้าย เช่น "ΔFDI_GDP" หรือ "Δ²RDG_GDP (t-2)" — แกะสัญลักษณ์/lag
    ออกก่อน หาโค้ดตัวแปรฐานใน VARIABLE_LABELS แล้วประกอบกลับเป็น "Δ ชื่อเต็ม (ย่อ) (t-n)"
    ถ้าหาโค้ดฐานไม่เจอในพจนานุกรม จะคืนป้ายเดิมแบบไม่แปลง (เหมือนพฤติกรรมเดิม)"""
    m = re.match(r"^(Δ²?)([A-Za-z][A-Za-z0-9_]*)(\s*\(t-\d+\))?$", code)
    if m:
        diff_symbol, base_code, lag_part = m.groups()
        base_label = VARIABLE_LABELS.get(base_code)
        if base_label:
            if " : " in base_label:
                full_name, abbr = base_label.split(" : ", 1)
                base_display = f"{full_name} ({abbr})"
            else:
                base_display = base_label
            return f"{diff_symbol} {base_display}{lag_part or ''}"
        return str(code)

    label = VARIABLE_LABELS.get(code)
    if not label:
        return str(code)
    if " : " in label:
        full_name, abbr = label.split(" : ", 1)
        return f"{full_name} ({abbr})"
    return label


def _var_full_name(code: str) -> str:
    """คืนเฉพาะชื่อเต็มภาษาไทยของตัวแปร (ไม่มีรหัสย่อต่อท้าย) ใช้ในข้อความอธิบาย
    เช่น การ์ดผลกระทบที่อยากพูดถึงตัวแปรด้วยชื่อเต็มล้วน ๆ อ่านลื่นกว่า"""
    label = VARIABLE_LABELS.get(code)
    if not label:
        return str(code)
    if " : " in label:
        return label.split(" : ", 1)[0]
    return label


# แกะรหัสตัวแปรดิบ เช่น "d1_FDI_GDP_lag0" -> (base="FDI_GDP", diff=1, lag=0)
# "ECM_lag1" -> (base="ECM", diff=0, lag=1) | "ln_HDI" -> (base="ln_HDI", diff=0, lag=0)
_VAR_CODE_RE = re.compile(r"^(?:d(?P<diff>[12])_)?(?P<base>.+?)(?:_lag(?P<lag>\d+))?$")


def _parse_variable_code(code: str):
    m = _VAR_CODE_RE.match(str(code).strip())
    if not m:
        return str(code).strip(), 0, 0
    base = m.group("base")
    diff = int(m.group("diff")) if m.group("diff") else 0
    lag = int(m.group("lag")) if m.group("lag") else 0
    return base, diff, lag


def _significance_stars(p_value) -> str:
    try:
        p = float(p_value)
    except (TypeError, ValueError):
        return ""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


def _format_coefficient_cell(coef_value, p_value, diff: int, lag: int, show_significance: bool) -> str:
    try:
        coef_text = f"{float(coef_value):.4f}"
    except (TypeError, ValueError):
        return "-"
    parts = []
    if lag > 0:
        parts.append(f"(t-{lag})")
    parts.append(coef_text)
    if show_significance:
        star = _significance_stars(p_value)
        if star:
            parts.append(star)
    if diff == 1:
        parts.append("Δ")
    elif diff == 2:
        parts.append("Δ²")
    return " ".join(parts)


def _extract_raw_coefficients(df: pd.DataFrame) -> dict:
    """ดึงค่าสัมประสิทธิ์ดิบ (ตัวเลขจริง ไม่ใช่สตริงจัดรูปแบบแบบใน _merge_coefficient_tables)
    จากตาราง lr_table/sr_table ที่ได้จาก build_coefficient_tables()
    คืนค่าเป็น dict: base_var -> {"coef", "p", "diff", "lag", "raw_code"}
    ถ้าตัวแปรฐานเดียวกันมีหลายแถว (เช่น มีหลาย lag) จะเก็บแถวสุดท้ายไว้ ให้ตรงกับ
    ตัวเลขที่แสดงในตารางสัมประสิทธิ์รวมที่ผู้ใช้เห็นอยู่แล้วในหน้าหลัก"""
    var_col, coef_col = df.columns[0], df.columns[1]
    p_col = df.columns[2] if len(df.columns) > 2 else None
    out = {}
    for _, row in df.iterrows():
        base, diff, lag = _parse_variable_code(row[var_col])
        try:
            coef = float(row[coef_col])
        except (TypeError, ValueError):
            continue
        p_val = None
        if p_col is not None:
            try:
                p_val = float(row[p_col])
            except (TypeError, ValueError):
                p_val = None
        out[base] = {"coef": coef, "p": p_val, "diff": diff, "lag": lag, "raw_code": row[var_col]}
    return out


def _merge_coefficient_tables(lr_table: pd.DataFrame, sr_table: pd.DataFrame) -> pd.DataFrame:
    """แปลงตารางระยะยาว/ระยะสั้นจาก TFP.py (คอลัมน์: รหัสตัวแปรดิบ, สัมประสิทธิ์, p-value)
    เป็นตารางเดียวแบบฟอร์มรายงานทางการ — คอลัมน์ระยะยาวแสดงเฉพาะค่าสัมประสิทธิ์
    (ไม่มีดาว/Δ/lag) ส่วนคอลัมน์ระยะสั้นแสดง (t-N) + ค่า + ดาวนัยสำคัญ + Δ/Δ²

    หมายเหตุ: รูปแบบรหัสตัวแปร (d1_/d2_ prefix, _lagN suffix) และรายชื่อตัวแปรเต็ม
    อิงจากตัวอย่างข้อมูลจริงที่ได้รับมา — ถ้า TFP.py มีตัวแปรอื่นเพิ่มเติมนอกเหนือจาก
    VARIABLE_LABELS ด้านบน ให้เพิ่มรายการในดิกชันนารีนั้น"""

    def build_map(df: pd.DataFrame, show_significance: bool) -> dict:
        var_col, coef_col = df.columns[0], df.columns[1]
        p_col = df.columns[2] if len(df.columns) > 2 else None
        out = {}
        for _, row in df.iterrows():
            base, diff, lag = _parse_variable_code(row[var_col])
            p_val = row[p_col] if p_col is not None else None
            out[base] = _format_coefficient_cell(row[coef_col], p_val, diff, lag, show_significance)
        return out

    lr_map = build_map(lr_table, show_significance=False)
    sr_map = build_map(sr_table, show_significance=True)

    rows = []
    for base in VARIABLE_ORDER:
        label = VARIABLE_LABELS.get(base, base)
        lr_val = lr_map.get(base, "n.a." if base == "ECM" else "-")
        sr_val = sr_map.get(base, "-")
        rows.append([label, lr_val, sr_val])

    # กันตกหล่น: ตัวแปรที่มีในข้อมูลจริงแต่ไม่อยู่ใน VARIABLE_ORDER ด้านบน
    known = set(VARIABLE_ORDER)
    extra_bases = [b for b in list(lr_map) + list(sr_map) if b not in known]
    for base in dict.fromkeys(extra_bases):
        rows.append([VARIABLE_LABELS.get(base, base), lr_map.get(base, "-"), sr_map.get(base, "-")])

    return pd.DataFrame(
        rows,
        columns=["ตัวแปร", "ค่าสัมประสิทธิ์\nสมการระยะยาว", "ค่าสัมประสิทธิ์\nสมการระยะสั้น"],
    )


def _docx_set_thai_font(run, size=11, bold=False, color=None, name="Sarabun"):
    """ตั้งฟอนต์ไทยให้ run ของ python-docx ให้ครบทั้ง ascii/hAnsi/cs (จำเป็นสำหรับ
    ภาษาไทยใน Word เพราะ Word แยก font ของอักษรตะวันตก/complex-script ออกจากกัน
    ถ้าตั้งแค่ run.font.name เฉยๆ ตัวอักษรไทยอาจไม่ถูกวาดด้วยฟอนต์ที่ตั้งไว้)"""
    run.font.name = name
    run.font.size = DocxPt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(docx_qn("w:rFonts"))
    if rFonts is None:
        rFonts = docx_OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(docx_qn("w:ascii"), name)
    rFonts.set(docx_qn("w:hAnsi"), name)
    rFonts.set(docx_qn("w:cs"), name)


def _docx_shade_cell(cell, hex_color: str):
    """ใส่สีพื้นหลังให้เซลล์ตาราง python-docx (ไม่มี API สำเร็จรูปให้ใช้ ต้องแทรก
    element w:shd เข้าไปใน tcPr เอง)"""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = docx_OxmlElement("w:shd")
    shd.set(docx_qn("w:val"), "clear")
    shd.set(docx_qn("w:color"), "auto")
    shd.set(docx_qn("w:fill"), hex_color)
    tcPr.append(shd)


def _docx_add_bottom_border(paragraph, color="0F2B46", size=12):
    """วาดเส้นคั่นบาง ๆ ใต้ย่อหน้า (ใช้แทนเส้นคั่นใต้ชื่อเรื่อง เหมือนในไฟล์ PDF เดิม)"""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = docx_OxmlElement("w:pBdr")
    bottom = docx_OxmlElement("w:bottom")
    bottom.set(docx_qn("w:val"), "single")
    bottom.set(docx_qn("w:sz"), str(size))
    bottom.set(docx_qn("w:space"), "1")
    bottom.set(docx_qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _docx_add_runs_with_bold(paragraph, text: str, size=11, bold=False, color=None):
    """แตกข้อความที่มี **ตัวหนา** แบบ markdown ง่ายๆ ออกเป็นหลาย run ใน python-docx
    (ไม่เหมือน reportlab ที่ parse <b> ให้เองจาก markup เดียว)"""
    parts = re.split(r"(\*\*.+?\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            _docx_set_thai_font(run, size=size, bold=True, color=color)
        else:
            run = paragraph.add_run(part)
            _docx_set_thai_font(run, size=size, bold=bold, color=color)


def _docx_add_md_line(doc: "Document", line: str, navy_color):
    """แปลงข้อความ markdown แบบง่าย ๆ ที่ Gemini ส่งกลับมา (##, -, **bold**) เป็น
    ย่อหน้าใน python-docx Document — ตรรกะเดียวกับ _md_line_to_flowable ฝั่ง PDF เดิม
    แถวตาราง markdown (|...|) ถูกข้ามไปเช่นกัน เพราะวาดตาราง TFP จริงแยกไว้แล้ว"""
    s = line.strip()
    if not s or set(s) <= set("|-: "):
        return
    if s.startswith("|"):
        return
    if s.startswith("### "):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = DocxPt(4)
        p.paragraph_format.space_after = DocxPt(3)
        _docx_add_runs_with_bold(p, s[4:], size=12, bold=True, color=navy_color)
        return
    if s.startswith("## "):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = DocxPt(6)
        p.paragraph_format.space_after = DocxPt(4)
        _docx_add_runs_with_bold(p, s[3:], size=13, bold=True, color=navy_color)
        return
    if s.startswith("# "):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = DocxPt(6)
        p.paragraph_format.space_after = DocxPt(4)
        _docx_add_runs_with_bold(p, s[2:], size=15, bold=True, color=navy_color)
        return
    if s.startswith(("- ", "• ", "* ")):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = DocxMm(5)
        p.paragraph_format.space_after = DocxPt(2)
        bullet_run = p.add_run("•  ")
        _docx_set_thai_font(bullet_run, size=11)
        _docx_add_runs_with_bold(p, s.lstrip("-•* "), size=11)
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_after = DocxPt(2)
    _docx_add_runs_with_bold(p, s, size=11)


_MPL_THAI_FONT_LOADED = False


def _register_thai_font_matplotlib():
    """โหลดฟอนต์ Sarabun (ไฟล์เดียวกับที่ใช้ฝั่ง reportlab) เข้า matplotlib font manager
    เพื่อให้ตัวอักษรไทยบนกราฟที่ render เป็นรูปภาพ (สำหรับฝังในไฟล์ Word) อ่านออกได้
    ปกติ ไม่ใช่สี่เหลี่ยมกล่องขาด (tofu) — ทำครั้งเดียวแล้วจำไว้ ไม่ต้องโหลดซ้ำทุกครั้ง"""
    global _MPL_THAI_FONT_LOADED
    if _MPL_THAI_FONT_LOADED:
        return
    try:
        fm.fontManager.addfont(os.path.join(FONT_DIR, "Sarabun-Regular.ttf"))
        fm.fontManager.addfont(os.path.join(FONT_DIR, "Sarabun-Bold.ttf"))
        plt.rcParams["font.family"] = "Sarabun"
    except FileNotFoundError:
        pass
    _MPL_THAI_FONT_LOADED = True


def _build_tfpi_chart_png(tfpi_series: pd.Series) -> bytes:
    """สร้างกราฟเส้นแนวโน้มดัชนี TFPI รายปีแบบเรียบหรู (เส้นสีกรมท่าของแบรนด์ + จุดวงกลม
    สีส้มขอบขาว + พื้นที่ใต้เส้นไล่สีจาง ๆ + เส้น grid บาง ๆ แนวนอน ไม่มีกรอบขวา/บน)
    คืนค่าเป็นรูป PNG พื้นหลังโปร่งใส ความละเอียดสูง สำหรับฝังในไฟล์ Word — python-docx
    ไม่มีกราฟ native แบบ python-pptx จึงต้อง render เป็นรูปภาพแทน"""
    _register_thai_font_matplotlib()
    navy = "#0F2B46"
    orange = "#F97316"

    x_labels = [str(y) for y in tfpi_series.index]
    y_vals = tfpi_series.values.astype(float)
    x_pos = list(range(len(x_labels)))

    fig, ax = plt.subplots(figsize=(9.4, 3.6), dpi=200)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    ax.plot(x_pos, y_vals, color=navy, linewidth=2.3, zorder=3, solid_capstyle="round")
    y_floor = min(y_vals) - (max(y_vals) - min(y_vals)) * 0.15 if max(y_vals) != min(y_vals) else min(y_vals) - 1
    ax.fill_between(x_pos, y_vals, y_floor, color=navy, alpha=0.08, zorder=1)
    ax.scatter(x_pos, y_vals, color=orange, s=46, zorder=4, edgecolors="white", linewidths=1.1)

    ax.set_ylim(bottom=y_floor)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#C7CFD9")
    ax.spines["bottom"].set_color("#C7CFD9")
    ax.grid(axis="y", color="#E9ECF1", linestyle="--", linewidth=0.7, zorder=0)
    ax.tick_params(colors="#5B6B7C", labelsize=9, length=0)

    # โชว์ label แกน x เป็นช่วง ๆ กันแน่นเกินไปเวลามีหลายปี (เหมือนกราฟ Altair ฝั่งเว็บ)
    step = max(1, round(len(x_labels) / 12))
    tick_idx = list(range(0, len(x_labels), step))
    if tick_idx[-1] != len(x_labels) - 1:
        tick_idx.append(len(x_labels) - 1)
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([x_labels[i] for i in tick_idx])

    for spine in ("left", "bottom"):
        ax.spines[spine].set_linewidth(0.8)

    fig.tight_layout()
    buffer = BytesIO()
    fig.savefig(buffer, format="png", transparent=True, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def build_word_report(summary_text: str, lr_table: pd.DataFrame, sr_table: pd.DataFrame,
                       lr_adj_r2: float, sr_adj_r2: float, model_df: pd.DataFrame) -> bytes:
    """สร้างไฟล์ Word (.docx) ที่แก้ไขได้ แต่จัดหน้าตาให้เหมือนไฟล์ PDF เดิมที่เคย export
    (หัวกระดาษโลโก้คู่ สอวช./สวค. อยู่กึ่งกลาง, ชื่อเรื่อง, ตารางค่าสัมประสิทธิ์, เนื้อหาสรุป
    จาก AI, ท้ายกระดาษ) — แทนที่ build_pdf_report เดิมที่ export เป็น PDF อ่านอย่างเดียว"""
    NAVY = DocxRGBColor(0x0F, 0x2B, 0x46)
    GREY = DocxRGBColor(0x80, 0x80, 0x80)
    WHITE = DocxRGBColor(0xFF, 0xFF, 0xFF)
    LIGHT_ROW = "EEF2F6"
    HEADER_FILL = "0F2B46"

    doc = Document()

    # --- ขนาดกระดาษ A4 + ระยะขอบ ให้เหมือนไฟล์ PDF เดิม (14mm บน/ล่าง, 18mm ซ้าย/ขวา) ---
    section = doc.sections[0]
    section.page_width = DocxMm(210)
    section.page_height = DocxMm(297)
    section.top_margin = DocxMm(14)
    section.bottom_margin = DocxMm(14)
    section.left_margin = DocxMm(18)
    section.right_margin = DocxMm(18)
    usable_width_mm = 210 - 18 - 18

    # ตั้งฟอนต์เริ่มต้นของเอกสารเป็น Sarabun เพื่อให้ข้อความที่ยังไม่ได้ตั้งฟอนต์เอง
    # (เช่น ที่ Word อาจเติมเอง) ไม่หลุดไปเป็นฟอนต์ default อื่น
    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Sarabun"
    normal_style.font.size = DocxPt(11)
    normal_rPr = normal_style.element.get_or_add_rPr()
    normal_rFonts = normal_rPr.find(docx_qn("w:rFonts"))
    if normal_rFonts is None:
        normal_rFonts = docx_OxmlElement("w:rFonts")
        normal_rPr.append(normal_rFonts)
    normal_rFonts.set(docx_qn("w:ascii"), "Sarabun")
    normal_rFonts.set(docx_qn("w:hAnsi"), "Sarabun")
    normal_rFonts.set(docx_qn("w:cs"), "Sarabun")

    # --- หัวกระดาษ: โลโก้ สอวช. + สวค. คู่กันตรงกลาง แล้วชื่อรายงานอยู่บรรทัดถัดมา ---
    logo1_path = os.path.join(APP_DIR, "สอวช_Logo.png")
    logo2_path = os.path.join(APP_DIR, "สวค_Logo.png")
    logo_specs = []
    if os.path.exists(logo1_path):
        logo_specs.append((logo1_path, 50, 25))
    if os.path.exists(logo2_path):
        logo_specs.append((logo2_path, 20, 20))

    if logo_specs:
        logo_table = doc.add_table(rows=1, cols=len(logo_specs))
        logo_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for cell, (path, w, h) in zip(logo_table.rows[0].cells, logo_specs):
            cell.width = DocxMm(w + 8)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run()
            run.add_picture(path, width=DocxMm(w), height=DocxMm(h))
        doc.add_paragraph()

    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _docx_add_runs_with_bold(title_p, "บทสรุปสำหรับนำเสนอ", size=18, bold=True, color=NAVY)

    subtitle_p = doc.add_paragraph()
    subtitle_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_p.paragraph_format.space_after = DocxPt(6)
    _docx_add_runs_with_bold(
        subtitle_p, "ผลิตภาพการผลิตรวม (Total Factor Productivity) ของประเทศไทย",
        size=12, color=NAVY,
    )
    _docx_add_bottom_border(subtitle_p, color="0F2B46", size=12)

    doc.add_paragraph()

    # --- กราฟแนวโน้มดัชนี TFPI รายปี (รูปภาพเรียบหรู ฝังไว้ก่อนตารางรายละเอียด) ---
    tfpi_series = model_df[DEP_VAR].dropna().sort_index()
    if len(tfpi_series) >= 2:
        chart_title_p = doc.add_paragraph()
        chart_title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        chart_title_p.paragraph_format.space_after = DocxPt(4)
        _docx_add_runs_with_bold(
            chart_title_p, "แนวโน้มดัชนีผลิตภาพการผลิตรวม (TFPI) รายปี",
            size=13, bold=True, color=NAVY,
        )
        chart_png = _build_tfpi_chart_png(tfpi_series)
        chart_p = doc.add_paragraph()
        chart_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        chart_run = chart_p.add_run()
        chart_run.add_picture(BytesIO(chart_png), width=DocxMm(usable_width_mm))
        doc.add_paragraph()

    # --- ตารางผลการทดสอบปัจจัยด้าน ววน. ที่มีต่อผลิตภาพทางเศรษฐกิจไทย ---
    table_title_p = doc.add_paragraph()
    table_title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    table_title_p.paragraph_format.space_after = DocxPt(4)
    _docx_add_runs_with_bold(
        table_title_p,
        "ตารางผลการทดสอบปัจจัยด้านวิทยาศาสตร์ วิจัย และนวัตกรรม (ววน.) "
        "ที่มีต่อผลิตภาพทางเศรษฐกิจไทย",
        size=13, bold=True, color=NAVY,
    )

    combined_table = _merge_coefficient_tables(lr_table, sr_table)
    n_cols = len(combined_table.columns)
    col_props = [0.46, 0.27, 0.27]

    table = doc.add_table(rows=1, cols=n_cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr_cells = table.rows[0].cells
    for i, col_name in enumerate(combined_table.columns):
        cell = hdr_cells[i]
        cell.width = DocxMm(usable_width_mm * col_props[i])
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        lines = str(col_name).split("\n")
        for j, ln in enumerate(lines):
            if j > 0:
                p.add_run().add_break()
            run = p.add_run(ln)
            _docx_set_thai_font(run, size=9, bold=True, color=WHITE)
        _docx_shade_cell(cell, HEADER_FILL)

    for row_i, row_vals in enumerate(combined_table.values.tolist()):
        cells = table.add_row().cells
        for col_i, val in enumerate(row_vals):
            cell = cells[col_i]
            cell.width = DocxMm(usable_width_mm * col_props[col_i])
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if col_i == 0 else WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(str(val))
            _docx_set_thai_font(run, size=9, bold=(col_i == 0), color=NAVY if col_i == 0 else None)
            if row_i % 2 == 1:
                _docx_shade_cell(cell, LIGHT_ROW)

    doc.add_paragraph()

    # แถว Adj. R² ต่อท้ายตาราง (ไม่ได้อยู่ในตัวตารางสัมประสิทธิ์ เพราะเป็นค่าประเมิน
    # คุณภาพของแต่ละสมการ ไม่ใช่ค่าสัมประสิทธิ์ของตัวแปร)
    r2_table = doc.add_table(rows=1, cols=n_cols)
    r2_table.style = "Table Grid"
    r2_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    r2_values = ["Adj. R²", f"{lr_adj_r2:.4f}", f"{sr_adj_r2:.4f}"]
    for i in range(n_cols):
        cell = r2_table.rows[0].cells[i]
        cell.width = DocxMm(usable_width_mm * col_props[i])
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(r2_values[i] if i < len(r2_values) else "")
        _docx_set_thai_font(run, size=9, bold=True)

    caption_p = doc.add_paragraph()
    caption_p.paragraph_format.space_before = DocxPt(4)
    _docx_add_runs_with_bold(
        caption_p,
        'หมายเหตุ: ***, **, * หมายถึง นัยสำคัญทางสถิติที่ระดับความเชื่อมั่น 99%, 95%, 90% '
        'ตามลำดับ | "-" หมายถึงตัวแปรที่ไม่ได้อยู่ในสมการนี้ | Δ และ Δ² หมายถึงผลต่างลำดับที่ 1 '
        'และ 2 ตามลำดับ',
        size=8, color=GREY,
    )

    doc.add_paragraph()

    # --- เนื้อหาสรุปจาก AI ---
    # ข้ามบรรทัดคำลงท้าย/ลายเซ็นที่ Gemini อาจแต่งมาเอง (เช่น "ขอแสดงความนับถือ",
    # "(นักเศรษฐศาสตร์)") เพราะเราใส่คำลงท้ายมาตรฐานเองด้านล่างแทน (เหมือนไฟล์ PDF เดิม)
    _signature_markers = ("ขอแสดงความนับถือ", "นักเศรษฐศาสตร์")
    for line in summary_text.split("\n"):
        if any(marker in line for marker in _signature_markers):
            continue
        _docx_add_md_line(doc, line, NAVY)

    doc.add_paragraph()
    footer_p = doc.add_paragraph()
    _docx_add_runs_with_bold(
        footer_p,
        f"จัดทำโดยระบบปัญญาประดิษฐ์ Google Gemini ({GEMINI_MODEL}) — "
        f"สร้างเมื่อวันที่ {thai_timestamp()}",
        size=8, color=GREY,
    )

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# ------------------------------------------------------------------------------
# สร้างไฟล์ PowerPoint สำหรับนำเสนอ (โลโก้มุมบนขวาทุกสไลด์, สรุปจาก AI
# แบ่งเป็นสไลด์ตามหัวข้อ, ตารางค่าสัมประสิทธิ์)
# ------------------------------------------------------------------------------
NAVY = RGBColor(0x0F, 0x2B, 0x46)
SLATE = RGBColor(0x4A, 0x55, 0x61)
LIGHT_GREY = RGBColor(0x9A, 0xA5, 0xB1)
ROW_TINT = RGBColor(0xEE, 0xF2, 0xF6)


def _parse_summary_sections(text: str):
    """แตกข้อความสรุปจาก Gemini (##, **หัวข้อ**, -/•/*) เป็นรายการ (หัวข้อ, [bullet, ...])
    เพื่อนำไปวางเป็นสไลด์แยกตามหัวข้อ ข้ามแถวตาราง markdown และลายเซ็นท้ายเอกสาร
    (ใช้ตรรกะเดียวกับ _md_line_to_flowable ฝั่ง PDF แต่คืนค่าเป็นข้อความล้วน
    เพราะ python-pptx ไม่ต้องการ XML markup แบบ ReportLab)

    หัวข้อย่อยที่มีเลขนำหน้าเดียวกับหัวข้อหลัก (เช่น "3." แล้วตามด้วย "3.1", "3.2")
    จะถูกรวมเข้าเป็นสไลด์เดียวกัน แทนที่จะแยกสไลด์ต่อหัวข้อย่อย เพื่อไม่ให้เนื้อหาที่
    ควรอยู่หน้าเดียวกันถูกกระจายออกเป็นหลายหน้าโดยไม่จำเป็น"""
    signature_markers = ("ขอแสดงความนับถือ", "นักเศรษฐศาสตร์")
    sections = []
    current_title = None
    current_bullets = []
    current_major = None  # เลขหัวข้อหลักของ current_title เช่น "3" จาก "3. ..." หรือ "3.1 ..."

    def _major_number(title: str):
        m = re.match(r"^(\d+)(?:\.\d+)?\.?\s", title + " ")
        return m.group(1) if m else None

    def _flush():
        if current_title is not None or current_bullets:
            sections.append((current_title or "สรุปภาพรวม", current_bullets))

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or set(line) <= set("|-: ") or line.startswith("|"):
            continue
        if any(marker in line for marker in signature_markers):
            continue
        heading_match = re.match(r"^#{1,3}\s*(.+)$", line)
        bold_only_match = re.match(r"^\*\*(.+?)\*\*:?$", line)
        if heading_match or bold_only_match:
            new_title = (heading_match.group(1) if heading_match else bold_only_match.group(1)).strip()
            new_major = _major_number(new_title)
            if (current_title is not None and new_major is not None
                    and new_major == current_major):
                # หัวข้อย่อยเลขเดียวกับหัวข้อหลักปัจจุบัน — รวมต่อในสไลด์เดิม
                # แทนการขึ้นสไลด์ใหม่ ใส่เป็นบรรทัดหัวข้อย่อยคั่นก่อนกลุ่ม bullet ถัดไป
                current_bullets.append(f"■ {new_title}")
                continue
            _flush()
            current_title = new_title
            current_major = new_major
            current_bullets = []
            continue
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", line).lstrip("-•* ").strip()
        if clean:
            current_bullets.append(clean)
    _flush()
    return sections


def _estimate_bullet_lines(bullet_text: str, chars_per_line: int = 68) -> float:
    """ประมาณจำนวนบรรทัดที่ bullet หนึ่งข้อความจะตัดคำ (word-wrap) ภายในกล่องข้อความ
    กว้าง ~11.3 นิ้ว ที่ขนาดฟอนต์ 15-16pt — ใช้ประมาณความสูงที่ต้องใช้จริง เพื่อกันเนื้อหา
    ล้นสไลด์ (คำนวณคร่าว ๆ พอเพียงสำหรับแบ่งหน้า ไม่ต้องแม่นยำระดับพิกเซล)"""
    return max(1.0, math.ceil(len(bullet_text) / chars_per_line))


def _chunk_bullets(bullets, max_lines_per_slide: float = 24.0):
    """แบ่งรายการ bullet ยาว ๆ ออกเป็นหลายสไลด์ ไม่ให้เนื้อหาล้นขอบล่างสไลด์เดียว
    แต่ละ bullet คิดน้ำหนักตามจำนวนบรรทัดที่ประมาณไว้ บวกพื้นที่ระยะห่างระหว่างข้อ
    (ปรับเพดานบรรทัดต่อสไลด์ขึ้นจาก 15 เป็น 24 เพื่อให้เนื้อหาของแต่ละหัวข้อ — รวมทั้ง
    หัวข้อย่อยที่ถูกรวมมาจาก _parse_summary_sections — ยุบอยู่ในสไลด์เดียวได้มากที่สุด
    ลดจำนวนสไลด์ '(ต่อ)' ที่ทำให้เนื้อหากระจายเกินความจำเป็น)"""
    chunks, current, lines_used = [], [], 0.0
    for bullet in bullets:
        weight = _estimate_bullet_lines(bullet) + 0.4  # เผื่อระยะห่าง (space_after) ระหว่างข้อ
        if current and lines_used + weight > max_lines_per_slide:
            chunks.append(current)
            current, lines_used = [], 0.0
        current.append(bullet)
        lines_used += weight
    if current:
        chunks.append(current)
    return chunks


def _add_logos_top_right(slide, prs, logo1_path: str, logo2_path: str):
    margin = Inches(0.3)
    height = Inches(0.55)
    paths = [p for p in (logo1_path, logo2_path) if os.path.exists(p)]
    pics = [slide.shapes.add_picture(p, 0, margin, height=height) for p in paths]
    if not pics:
        return
    gap = Inches(0.15)
    total_width = sum(pic.width for pic in pics) + gap * (len(pics) - 1)
    x = prs.slide_width - margin - total_width
    for pic in pics:
        pic.left = int(x)
        x += pic.width + gap


def _add_footer(slide, prs, footer_text: str):
    box = slide.shapes.add_textbox(
        Inches(0.5), prs.slide_height - Inches(0.45),
        prs.slide_width - Inches(1.0), Inches(0.35),
    )
    tf = box.text_frame
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    run = p.add_run()
    run.text = footer_text
    run.font.size = Pt(9)
    run.font.color.rgb = LIGHT_GREY
    run.font.name = "Sarabun"


ORANGE = RGBColor(0xF2, 0x81, 0x1D)


def _add_title_accent(slide, prs, x=Inches(0.8), y=Inches(1.22), width=Inches(0.55)):
    """ขีดเส้นสั้น ๆ สีส้มใต้หัวข้อสไลด์ — เพิ่มจุดเน้นเล็ก ๆ ให้สไลด์ดูมีดีไซน์
    มากกว่าปล่อยว่างระหว่างหัวข้อกับเนื้อหา (มินิมอล ไม่ใช่เส้นเต็มความกว้างสไลด์)"""
    bar = slide.shapes.add_shape(1, x, y, width, Pt(3.5))  # 1 = MSO_SHAPE.RECTANGLE
    bar.fill.solid()
    bar.fill.fore_color.rgb = ORANGE
    bar.line.fill.background()
    bar.shadow.inherit = False


def _add_page_number(slide, prs, page_no: int):
    """ใส่เลขหน้ามุมล่างขวาแบบเล็ก ๆ สีเทาอ่อน ช่วยให้สไลด์ดูครบองค์ประกอบขึ้น"""
    box = slide.shapes.add_textbox(
        prs.slide_width - Inches(1.0), prs.slide_height - Inches(0.45),
        Inches(0.6), Inches(0.35),
    )
    tf = box.text_frame
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    run = p.add_run()
    run.text = str(page_no)
    run.font.size = Pt(9)
    run.font.color.rgb = LIGHT_GREY
    run.font.name = "Sarabun"


def _blank_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def build_pptx_report(summary_text: str, lr_table: pd.DataFrame, sr_table: pd.DataFrame,
                       lr_adj_r2: float, sr_adj_r2: float, model_df: pd.DataFrame) -> bytes:
    logo1_path = os.path.join(APP_DIR, "สอวช_Logo.png")
    logo2_path = os.path.join(APP_DIR, "สวค_Logo.png")

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    footer_text = (f"บทสรุปสำหรับนำเสนอ TFP — จัดทำโดยระบบปัญญาประดิษฐ์ Google Gemini "
                    f"({GEMINI_MODEL}) — สร้างเมื่อวันที่ {thai_timestamp()}")

    # --- สไลด์ 1: หน้าปก ---
    slide = _blank_slide(prs)
    _add_logos_top_right(slide, prs, logo1_path, logo2_path)

    title_box = slide.shapes.add_textbox(Inches(0.8), Inches(2.7), Inches(11.7), Inches(1.3))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    run = p.add_run()
    run.text = "บทสรุปสำหรับนำเสนอ"
    run.font.size = Pt(40)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.name = "Sarabun"

    subtitle_box = slide.shapes.add_textbox(Inches(0.8), Inches(3.85), Inches(11.7), Inches(0.8))
    tf = subtitle_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = "ผลิตภาพการผลิตรวม (Total Factor Productivity) ของประเทศไทย"
    run.font.size = Pt(20)
    run.font.color.rgb = SLATE
    run.font.name = "Sarabun"

    date_box = slide.shapes.add_textbox(Inches(0.8), Inches(4.7), Inches(11.7), Inches(0.5))
    tf = date_box.text_frame
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = thai_timestamp()
    run.font.size = Pt(13)
    run.font.color.rgb = LIGHT_GREY
    run.font.name = "Sarabun"

    # --- สไลด์ตาราง ววน. (ย้ายมาไว้เป็นหน้าที่ 2 ต่อจากหน้าปกทันที) ---
    page_no = 1
    combined_table = _merge_coefficient_tables(lr_table, sr_table)
    slide = _blank_slide(prs)
    _add_logos_top_right(slide, prs, logo1_path, logo2_path)
    head = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(0.9))
    tf = head.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = "ตารางผลการทดสอบปัจจัยด้านวิทยาศาสตร์ วิจัย และนวัตกรรม (ววน.)"
    run.font.size = Pt(20)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.name = "Sarabun"
    _add_title_accent(slide, prs, y=Inches(1.05))

    n_rows, n_cols = combined_table.shape[0] + 1, combined_table.shape[1]
    tbl_x, tbl_y = Inches(0.6), Inches(1.4)
    tbl_w, tbl_h = Inches(12.1), Inches(5.6)
    gframe = slide.shapes.add_table(n_rows, n_cols, tbl_x, tbl_y, tbl_w, tbl_h)
    table = gframe.table
    table.columns[0].width = int(tbl_w * 0.46)
    table.columns[1].width = int(tbl_w * 0.27)
    table.columns[2].width = int(tbl_w * 0.27)

    for c, col_name in enumerate(combined_table.columns):
        cell = table.cell(0, c)
        cell.text = str(col_name).replace("\n", " ")
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        run = cell.text_frame.paragraphs[0].runs[0]
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        run.font.name = "Sarabun"

    for r, row in enumerate(combined_table.values.tolist(), start=1):
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(value)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if r % 2 else ROW_TINT
            run = cell.text_frame.paragraphs[0].runs[0]
            run.font.size = Pt(10.5)
            run.font.color.rgb = SLATE
            run.font.name = "Sarabun"
            run.font.bold = (c == 0)
    _add_footer(slide, prs, footer_text)
    _add_page_number(slide, prs, page_no)

    # --- สไลด์ 3: ตัวเลขสรุปคุณภาพแบบจำลอง ---
    page_no += 1
    slide = _blank_slide(prs)
    _add_logos_top_right(slide, prs, logo1_path, logo2_path)
    head = slide.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.7), Inches(0.7))
    p = head.text_frame.paragraphs[0]
    run = p.add_run()
    run.text = "คุณภาพของแบบจำลองที่ใช้วิเคราะห์"
    run.font.size = Pt(26)
    run.font.bold = True
    run.font.color.rgb = NAVY
    run.font.name = "Sarabun"
    _add_title_accent(slide, prs)

    card_specs = [
        ("สมการระยะยาว (Long-run)", lr_adj_r2),
        ("สมการระยะสั้น (Short-run ECM)", sr_adj_r2),
    ]
    card_w, card_h, gap = Inches(5.5), Inches(2.6), Inches(0.6)
    total_w = card_w * 2 + gap
    start_x = (prs.slide_width - total_w) / 2
    for i, (label, value) in enumerate(card_specs):
        x = start_x + i * (card_w + gap)
        y = Inches(2.2)
        card = slide.shapes.add_shape(1, x, y, card_w, card_h)  # 1 = MSO_SHAPE.RECTANGLE
        card.fill.solid()
        card.fill.fore_color.rgb = ROW_TINT
        card.line.color.rgb = LIGHT_GREY
        card.line.width = Pt(0.75)
        card.shadow.inherit = False
        tf = card.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p0 = tf.paragraphs[0]
        p0.alignment = PP_ALIGN.CENTER
        r0 = p0.add_run()
        r0.text = f"{value:.4f}"
        r0.font.size = Pt(44)
        r0.font.bold = True
        r0.font.color.rgb = NAVY
        r0.font.name = "Sarabun"
        p1 = tf.add_paragraph()
        p1.alignment = PP_ALIGN.CENTER
        r1 = p1.add_run()
        r1.text = f"Adj. R² — {label}"
        r1.font.size = Pt(15)
        r1.font.color.rgb = SLATE
        r1.font.name = "Sarabun"
    _add_footer(slide, prs, footer_text)
    _add_page_number(slide, prs, page_no)

    # --- เตรียมข้อมูล TFPI ไว้แนบกราฟแนวโน้มในสไลด์หัวข้อแรก (ภาพรวม) แทนที่จะ
    # แยกเป็นสไลด์กราฟเดี่ยวต่างหาก (ย้ายมารวมกับเนื้อหาหัวข้อ "1. สรุปภาพรวม...") ---
    tfpi_series = model_df[DEP_VAR].dropna().sort_index()

    # --- สไลด์ตามหัวข้อที่แตกจากสรุปของ AI (ภาพรวม / เปรียบเทียบ / ข้อเสนอแนะ) ---
    # เนื้อหาแต่ละหัวข้ออาจมี bullet ยาวเกินกว่าจะใส่ในสไลด์เดียว จึงแบ่งหน้าอัตโนมัติ
    # ด้วย _chunk_bullets แล้วต่อชื่อหัวข้อด้วย "(ต่อ)" ในสไลด์ถัดไป กันเนื้อหาล้นขอบล่าง
    # (ตัดบรรทัดขึ้นต้นแบบหนังสือราชการที่เรียกผู้บริหาร เช่น "เรียน ท่านผู้บริหาร..."
    # ออกก่อน — ดึกไม่ต้องการให้กลายเป็นสไลด์แยกในชุดสไลด์แสดงผลกลาง)
    sections = _parse_summary_sections(_web_summary_text(summary_text))
    for section_idx, (title, bullets) in enumerate(sections):
        if not bullets:
            continue
        is_first_section = (section_idx == 0) and len(tfpi_series) >= 2
        # หัวข้อ "เปรียบเทียบ..." ใส่กราฟแท่งย้อนหลังประกอบด้วย เพื่อให้เห็นภาพ
        # การเปลี่ยนแปลงชัดเจนขึ้น ไม่ใช่มีแต่ข้อความอย่างเดียว
        show_compare_chart = (not is_first_section) and ("เปรียบเทียบ" in title) and len(tfpi_series) >= 2
        chunks = _chunk_bullets(bullets)
        for chunk_idx, chunk in enumerate(chunks):
            slide_title = title if chunk_idx == 0 else f"{title} (ต่อ)"
            page_no += 1
            slide = _blank_slide(prs)
            _add_logos_top_right(slide, prs, logo1_path, logo2_path)
            head = slide.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.0), Inches(0.9))
            tf = head.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = slide_title
            run.font.size = Pt(26)
            run.font.bold = True
            run.font.color.rgb = NAVY
            run.font.name = "Sarabun"
            _add_title_accent(slide, prs)

            # เฉพาะสไลด์แรกของหัวข้อภาพรวม (แนบกราฟแนวโน้ม) หรือหัวข้อเปรียบเทียบ
            # (แนบกราฟแท่งย้อนหลัง): ลดความกว้างกล่องข้อความลงเพื่อเปิดพื้นที่ฝั่งขวา
            put_line_chart_here = is_first_section and chunk_idx == 0
            put_bar_chart_here = show_compare_chart and chunk_idx == 0
            put_chart_here = put_line_chart_here or put_bar_chart_here
            body_w = Inches(6.6) if put_chart_here else Inches(11.3)
            body = slide.shapes.add_textbox(Inches(0.9), Inches(1.6), body_w, Inches(5.15))
            tf = body.text_frame
            tf.word_wrap = True
            for i, bullet in enumerate(chunk):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.space_after = Pt(10)
                bullet_run = p.add_run()
                bullet_run.text = "●  "
                bullet_run.font.size = Pt(15)
                bullet_run.font.bold = True
                bullet_run.font.color.rgb = ORANGE
                bullet_run.font.name = "Sarabun"
                text_run = p.add_run()
                text_run.text = bullet
                text_run.font.size = Pt(15)
                text_run.font.color.rgb = SLATE
                text_run.font.name = "Sarabun"

            if put_line_chart_here:
                # กราฟแนวโน้มดัชนี TFPI รายปีเต็มช่วง (เดิมเคยแยกเป็นสไลด์กราฟต่างหาก
                # ย้ายมาแนบในสไลด์หัวข้อแรกแทน)
                chart_data = CategoryChartData()
                chart_data.categories = [str(y) for y in tfpi_series.index]
                chart_data.add_series("TFPI", tuple(float(v) for v in tfpi_series.values))
                gframe = slide.shapes.add_chart(
                    XL_CHART_TYPE.LINE_MARKERS,
                    Inches(7.8), Inches(1.6), Inches(4.6), Inches(5.15),
                    chart_data,
                )
                chart = gframe.chart
                chart.has_legend = False
                chart.has_title = True
                chart.chart_title.text_frame.text = "แนวโน้มดัชนี TFPI รายปี"
                ttl_run = chart.chart_title.text_frame.paragraphs[0].runs[0]
                ttl_run.font.size = Pt(12)
                ttl_run.font.bold = True
                ttl_run.font.color.rgb = NAVY
                ttl_run.font.name = "Sarabun"
                series = chart.plots[0].series[0]
                series.smooth = True
                series.format.line.color.rgb = NAVY
                series.format.line.width = Pt(2.0)
                series.marker.style = XL_MARKER_STYLE.CIRCLE
                series.marker.size = 6
                series.marker.format.fill.solid()
                series.marker.format.fill.fore_color.rgb = RGBColor(0xF2, 0x81, 0x1D)
                series.marker.format.line.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                series.marker.format.line.width = Pt(1.0)
                chart.category_axis.tick_labels.font.size = Pt(9)
                chart.category_axis.tick_labels.font.name = "Sarabun"
                chart.category_axis.format.line.color.rgb = LIGHT_GREY
                chart.value_axis.tick_labels.font.size = Pt(9)
                chart.value_axis.tick_labels.font.name = "Sarabun"
                chart.value_axis.tick_labels.number_format = "0.00"
                chart.value_axis.tick_labels.number_format_is_linked = False
                chart.value_axis.has_major_gridlines = True
                chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE9, 0xEC, 0xF1)
                chart.value_axis.major_gridlines.format.line.width = Pt(0.75)
                chart.value_axis.format.line.color.rgb = LIGHT_GREY
            elif put_bar_chart_here:
                recent = tfpi_series.tail(6)
                chart_data = CategoryChartData()
                chart_data.categories = [str(y) for y in recent.index]
                chart_data.add_series("TFPI", tuple(float(v) for v in recent.values))
                gframe = slide.shapes.add_chart(
                    XL_CHART_TYPE.COLUMN_CLUSTERED,
                    Inches(7.8), Inches(1.6), Inches(4.6), Inches(5.15),
                    chart_data,
                )
                chart = gframe.chart
                chart.has_legend = False
                chart.has_title = True
                chart.chart_title.text_frame.text = "TFPI ย้อนหลัง (ล่าสุด)"
                ttl_run = chart.chart_title.text_frame.paragraphs[0].runs[0]
                ttl_run.font.size = Pt(12)
                ttl_run.font.bold = True
                ttl_run.font.color.rgb = NAVY
                ttl_run.font.name = "Sarabun"
                series = chart.plots[0].series[0]
                series.format.fill.solid()
                series.format.fill.fore_color.rgb = ORANGE
                series.format.line.fill.background()
                chart.category_axis.tick_labels.font.size = Pt(9)
                chart.category_axis.tick_labels.font.name = "Sarabun"
                chart.category_axis.format.line.color.rgb = LIGHT_GREY
                chart.value_axis.tick_labels.font.size = Pt(9)
                chart.value_axis.tick_labels.font.name = "Sarabun"
                chart.value_axis.tick_labels.number_format = "0.00"
                chart.value_axis.tick_labels.number_format_is_linked = False
                chart.value_axis.has_major_gridlines = True
                chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE9, 0xEC, 0xF1)
                chart.value_axis.major_gridlines.format.line.width = Pt(0.75)
                chart.value_axis.format.line.color.rgb = LIGHT_GREY

            _add_footer(slide, prs, footer_text)
            _add_page_number(slide, prs, page_no)

    buffer = BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
# ------------------------------------------------------------------------------
# session state: ชุดตัวแปรที่ "ใช้งานจริง" ในสมการของ session นี้ แยกจาก
# LONG_RUN_VARS/SHORT_RUN_SPEC ที่ import มาจาก TFP.py (ค่า default ในไฟล์โค้ด
# จะไม่ถูกแก้ไข) — คณะวิจัยปรับชุดตัวแปรนี้ได้ผ่าน UI ด้านล่าง (ดู expander
# "ปรับตัวแปรในสมการ") โดยทุกการปรับต้องกรอกเหตุผล + พิมพ์คำยืนยันก่อนมีผลจริง
# ------------------------------------------------------------------------------
if "active_long_run_vars" not in st.session_state:
    st.session_state.active_long_run_vars = list(LONG_RUN_VARS)
if "active_short_run_spec" not in st.session_state:
    st.session_state.active_short_run_spec = list(SHORT_RUN_SPEC)
if "var_audit_log" not in st.session_state:
    st.session_state.var_audit_log = []  # แต่ละรายการ: เวลา/ตัดออก/เพิ่มกลับ/เหตุผล

# ------------------------------------------------------------------------------
# แถบด้านข้าง: โลโก้ + เมนูนำทาง + ช่องอัปโหลดข้อมูล
# ------------------------------------------------------------------------------
# หน้าที่มีในเมนู — เดิมแยก "Dashboard" (สรุปสั้น ๆ ตายตัว 5 ปี) กับ "พยากรณ์ TFP"
# (มุมมองเต็ม/โต้ตอบได้) เป็นคนละหน้า ทำให้ผู้ใช้งงว่าต้องดูหน้าไหน — รวมเป็นหน้า
# เดียวแล้ว ใช้ชื่อเมนู "Dashboard พยากรณ์ TFP" โดยเนื้อหาทั้งหมดยังอยู่ที่ page
# key เดิมคือ "forecast" (ไม่ได้เปลี่ยน key เพื่อไม่กระทบปุ่ม/ลิงก์อื่นที่อ้างถึง)
# ส่วนหน้าบทสรุปสำหรับนำเสนอเดิม (เดิมชื่อ "หน้าหลัก") อยู่ในกลุ่มเมนูรองด้านล่าง
# เปลี่ยนชื่อเป็น "สำหรับคณะวิจัยเท่านั้น" พร้อมล็อกด้วย username/password (ดูส่วน
# RESEARCH_USERNAME/RESEARCH_PASSWORD ด้านล่าง)
NAV_ITEMS = [
    ("Dashboard พยากรณ์ TFP", "forecast"),
    ("ทำความรู้จักตัวแปร", "data_vars"),
    ("คู่มือการใช้งาน", "manual"),
]

# กลุ่มเมนูรอง (แสดงแยกด้วยเส้นคั่น ใต้กลุ่มเมนูหลักด้านบน) — งานที่จำกัดสิทธิ์
# เฉพาะคณะวิจัยที่ต้องล็อกอินก่อนถึงจะเข้าดูได้ ("ผลการวิเคราะห์" และ
# "รายงานสรุปสำหรับนำเสนอ" ย้ายมาไว้ในกลุ่มนี้แทนกลุ่มเมนูหลักด้านบน)
NAV_ITEMS_SECONDARY = [
    ("สำหรับคณะวิจัยเท่านั้น", "home"),
    ("จัดการข้อมูลอัตโนมัติ", "data_admin"),
    ("ตั้งค่าระบบ", "settings"),
]

if "page" not in st.session_state:
    st.session_state.page = "forecast"

# บัญชีสำหรับเข้าหน้า "สำหรับคณะวิจัยเท่านั้น" — อ่านจาก .streamlit/secrets.toml
# แทนการฝังในโค้ดตรงๆ (ไฟล์ secrets.toml ต้องมี RESEARCH_USERNAME / RESEARCH_PASSWORD
# และไม่ควร push ขึ้น git — ใส่ไว้ใน .gitignore ด้วย)
try:
    RESEARCH_USERNAME = st.secrets["RESEARCH_USERNAME"]
    RESEARCH_PASSWORD = st.secrets["RESEARCH_PASSWORD"]
    _research_login_config_error = None
except (KeyError, FileNotFoundError):
    RESEARCH_USERNAME = None
    RESEARCH_PASSWORD = None
    _research_login_config_error = (
        "ยังไม่ได้ตั้งค่า RESEARCH_USERNAME / RESEARCH_PASSWORD ใน .streamlit/secrets.toml "
        "จึงยังเข้าหน้านี้ไม่ได้ — กรุณาเพิ่มค่าทั้งสองในไฟล์ secrets.toml ก่อน"
    )
if "research_authenticated" not in st.session_state:
    st.session_state.research_authenticated = False

with st.sidebar:
    _logo_divider_height = max(_LOGO1_SIZE, _LOGO2_SIZE) - 12
    st.markdown(
        f'<div class="sidebar-logo-card">'
        f'{logo1_html}'
        f'<div style="width:1px;height:{_logo_divider_height}px;background:var(--card-border);"></div>'
        f'{logo2_html}</div>',
        unsafe_allow_html=True,
    )
    # หมายเหตุ: โลโก้สถาบันการศึกษา (มหาวิทยาลัย + ภาควิชา) ที่เคยแสดงเป็นแถวที่ 2
    # ตรงนี้ ถูกย้ายไปรวมกับข้อมูลผู้จัดทำและเลขเวอร์ชันแอปในกล่องมุมขวาบนแทนแล้ว

    # ----- ส่วน "ข้อมูล" (ปุ่มดึงข้อมูลอัตโนมัติ) — ย้ายมาไว้บนสุดของแถบเมนู
    # ต่อจากโลโก้ ก่อนเมนูหลัก เพราะเป็นขั้นตอนแรกที่ผู้ใช้ต้องทำก่อนดูหน้าอื่น -----
    st.markdown(
        f'<div class="sidebar-section-label">{icon("database", 14, 1.6)}<span>ข้อมูล</span></div>',
        unsafe_allow_html=True,
    )
    if st.button("คลิกดึงข้อมูลอัตโนมัติ", use_container_width=True, key="nav_top_fetch"):
        st.session_state.pop("gsheet_load_error", None)
        try:
            with st.spinner("กำลังดึงข้อมูลอัตโนมัติ..."):
                st.session_state.gsheet_raw_df = _load_data_gsheet_with_optional_url(
                    st.session_state.get("custom_gsheet_url")
                )
            st.session_state.gsheet_loaded_at = now_th()
            _log_fetch_event()
        except Exception as e:
            st.session_state.gsheet_load_error = str(e)
            st.session_state.pop("gsheet_raw_df", None)
    if st.session_state.get("gsheet_load_error"):
        st.markdown(
            status_banner("error", f"ดึงข้อมูลไม่สำเร็จ: {st.session_state.gsheet_load_error}"),
            unsafe_allow_html=True,
        )
    elif "gsheet_raw_df" in st.session_state:
        st.markdown(
            status_banner("success", f"ดึงข้อมูลล่าสุดเมื่อ {st.session_state.gsheet_loaded_at.strftime('%H:%M:%S')}"),
            unsafe_allow_html=True,
        )
    st.caption("ดึงข้อมูล → รันโมเดล → สรุปผลอัตโนมัติ")
    st.markdown("---")

    for i, (label, page_key) in enumerate(NAV_ITEMS):
        is_active = st.session_state.page == page_key
        if st.button(
            label,
            key=f"nav_main_{i}_{page_key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state.page = page_key
            st.rerun()

    # ปุ่มออกจากระบบ — โชว์เฉพาะตอนล็อกอินเข้าหน้า "สำหรับคณะวิจัยเท่านั้น" อยู่แล้ว
    if st.session_state.research_authenticated:
        if st.button("ออกจากระบบ (คณะวิจัย)", use_container_width=True, key="nav_logout"):
            st.session_state.research_authenticated = False
            st.session_state.page = "forecast"
            st.rerun()

    st.markdown("---")
    st.markdown(
        f'<div class="sidebar-section-label">{icon("lock", 14, 1.6)}<span>สำหรับคณะวิจัย</span></div>',
        unsafe_allow_html=True,
    )
    for i, (label, page_key) in enumerate(NAV_ITEMS_SECONDARY):
        is_active = st.session_state.page == page_key
        if st.button(
            label,
            key=f"nav_sec_{i}_{page_key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state.page = page_key
            st.rerun()

    # ป้ายข้อมูลผู้จัดทำ + โลโก้มหาวิทยาลัย/ภาควิชา + เวอร์ชันแอป — วางไว้ท้าย
    # แถบเมนูด้านซ้าย (เล็ก ๆ ไม่เกะกะ) แทนที่จะลอยทับเนื้อหาแบบเดิม
    st.markdown(_corner_badge_html, unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# รันโมเดล (ถ้ามีไฟล์อัปโหลด) — คำนวณผลลัพธ์ทั้งหมดไว้ก่อน เพื่อนำไปแสดงในการ์ด
# สรุปสถานะที่หัวหน้าเพจ (metric cards) และในแต่ละหมวดด้านล่าง
# ------------------------------------------------------------------------------
result_ready = False
diag_table_display = None
n_pass = n_watch = n_fail = 0
adj_r2_lr = adj_r2_sr = None
vars_customized = False
lr_raw_map = {}
sr_raw_map = {}

if "gsheet_raw_df" in st.session_state:
    active_lr_vars = st.session_state.active_long_run_vars
    active_sr_spec = st.session_state.active_short_run_spec
    default_sr_bases = [c for c, _, _ in SHORT_RUN_SPEC]
    active_sr_bases = [c for c, _, _ in active_sr_spec]

    with st.spinner("กำลังรันโมเดล..."):
        raw = st.session_state.gsheet_raw_df
        model_df = build_model_frame(raw)
        dep_ln = "ln_" + DEP_VAR
        lr_res, lr_resid = run_long_run(model_df, dep_ln, active_lr_vars)
        sr_res = run_short_run(model_df, dep_ln, active_sr_spec, lr_resid)

    if sr_res is None:
        st.error("รันสมการระยะสั้นไม่สำเร็จ (พารามิเตอร์ >= observations) — ตรวจสอบข้อมูลนำเข้า")
    else:
        lr_table, sr_table = build_coefficient_tables(lr_res, sr_res)
        combined_table = _merge_coefficient_tables(lr_table, sr_table)
        lr_raw_map = _extract_raw_coefficients(lr_table)
        sr_raw_map = _extract_raw_coefficients(sr_table)
        adj_r2_lr = summary_adj_r2(lr_res)
        adj_r2_sr = summary_adj_r2(sr_res)
        vars_customized = (active_lr_vars != list(LONG_RUN_VARS) or active_sr_bases != default_sr_bases)

        try:
            diag_table = run_diagnostics(model_df, dep_ln, active_lr_vars, lr_res, sr_res, lr_resid,
                                          short_run_spec=active_sr_spec)
            diag_table_display = diag_table.copy()
            diag_table_display["รายการ"] = diag_table_display["รายการ"].apply(var_label_with_abbr)
            n_fail = int((diag_table["สถานะ"] == "🔴 ไม่ผ่าน").sum())
            n_watch = int(diag_table["สถานะ"].str.startswith("🟡").sum())
            n_pass = int(len(diag_table) - n_fail - n_watch)
        except Exception as e:
            st.info(f"ไม่สามารถรันตารางตรวจสอบข้อสมมติฐานได้ครบทุกรายการ: {e}")

        result_ready = True

# ------------------------------------------------------------------------------
# เนื้อหาของแต่ละหน้า แยกตามเมนูด้านซ้าย: "สำหรับคณะวิจัยเท่านั้น" (บทสรุปสำหรับนำเสนอ
# เดิม — ต้องล็อกอินก่อนถึงจะเห็น) กับ "Dashboard" (กราฟแนวโน้ม TFP + ตัวแปรอิสระ
# ที่เปิดให้บุคคลภายนอกเข้าชมได้โดยไม่ต้องล็อกอิน)
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# ฟังก์ชันวาดกราฟเส้น/พยากรณ์ ARIMA — อยู่ใน scope กลาง (ไม่ผูกกับหน้าใดหน้าหนึ่ง)
# เพราะทั้งหน้า Dashboard (สรุปย่อ) และหน้า "พยากรณ์ TFP" (แบบเต็ม/โต้ตอบได้)
# ต้องเรียกใช้ร่วมกัน
# ------------------------------------------------------------------------------
def _nice_line_chart(series: pd.Series, color: str = "#F97316", height: int = 340):
    """สร้างกราฟเส้นด้วย Altair แทน st.line_chart เดิม เพื่อให้ดูสวยและอ่านง่าย
    ขึ้นกว่าเดิม: เส้นโค้งมน มีพื้นที่ใต้เส้นแบบไล่สีจาง ๆ, เส้น grid บางๆ,
    และ label บนแกนปีที่สุ่มแสดงเป็นช่วง ๆ (ไม่ยัดทุกปีจนอ่านไม่ออก) พร้อม
    tooltip บอกปีและค่าที่ชี้เมื่อเอาเมาส์ไปวาง — และปีบนแกน x เป็น string
    (ordinal) เสมอ กัน Vega-Lite ตีความเป็นตัวเลขแล้วใส่ , คั่นหลักพัน"""
    s = series.copy()
    s.index = s.index.map(str)
    df = s.reset_index()
    df.columns = ["ปี", "ค่า"]

    n = len(df)
    step = max(1, round(n / 12))
    tick_vals = df["ปี"].iloc[::step].tolist()
    if df["ปี"].iloc[-1] not in tick_vals:
        tick_vals.append(df["ปี"].iloc[-1])

    base = alt.Chart(df).encode(
        x=alt.X(
            "ปี:O", sort=None, title=None,
            axis=alt.Axis(values=tick_vals, labelAngle=0, grid=False,
                           domain=False, tickColor="#E9ECF1",
                           labelColor="#5B6B7C", labelFontSize=11, labelPadding=6),
        ),
        y=alt.Y(
            "ค่า:Q", title=None,
            axis=alt.Axis(grid=True, gridColor="#EEF1F5", gridDash=[3, 3],
                           domain=False, tickColor="#E9ECF1",
                           labelColor="#5B6B7C", labelFontSize=11),
        ),
        tooltip=[
            alt.Tooltip("ปี:O", title="ปี"),
            alt.Tooltip("ค่า:Q", title="ค่า", format=".4f"),
        ],
    )
    area = base.mark_area(
        interpolate="monotone",
        line=False,
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color=color, offset=0),
                alt.GradientStop(color="#FFFFFF", offset=1),
            ],
            x1=1, x2=1, y1=1, y2=0,
        ),
        opacity=0.35,
    )
    line = base.mark_line(
        interpolate="monotone", color=color, strokeWidth=2.6,
        point=alt.OverlayMarkDef(filled=True, size=32, color=color, stroke="#FFFFFF", strokeWidth=1.6),
    )
    chart = (
        (area + line)
        .properties(width="container", height=height, padding={"left": 4, "right": 10, "top": 8, "bottom": 4})
        .configure_view(strokeWidth=0)
        .configure_axis(labelFont=FONT_FAMILY, titleFont=FONT_FAMILY)
    )
    st.altair_chart(chart, use_container_width=True)

@st.cache_data(show_spinner=False)
def _auto_arima_forecast(series: pd.Series, periods: int,
                          max_p: int = 4, max_d: int = 2, max_q: int = 4):
    """หาโมเดล ARIMA(p,d,q) ที่เหมาะกับข้อมูลที่สุดด้วยวิธี grid search
    (ลองทุกชุด p,d,q ในช่วงที่กำหนด แล้วเลือกชุดที่ค่า AIC ต่ำที่สุด — AIC ยิ่งต่ำ
    ยิ่งหมายถึงโมเดลอธิบายข้อมูลได้ดีโดยไม่ซับซ้อนเกินจำเป็น) จากนั้นพยากรณ์ล่วงหน้า
    `periods` ปี พร้อมช่วงความเชื่อมั่น 95%

    คืนค่า (forecast_df, order) โดย forecast_df มี index เป็นปีในอนาคต และ
    คอลัมน์ mean / lower / upper ส่วน order คือ (p, d, q) ที่เลือกใช้จริง
    ถ้าหาโมเดลที่ fit ได้ไม่สำเร็จเลย จะ fallback เป็น random walk with drift (0,1,0)"""
    y = series.astype(float).values

    # หาลำดับ differencing (d) ที่เหมาะสมก่อนด้วย ADF test (Augmented Dickey-Fuller)
    # แทนที่จะปล่อยให้ AIC เป็นตัวเลือก d เอง เพราะ AIC เปรียบเทียบข้าม d ต่างกัน
    # ไม่ได้ตรงๆ (ข้อมูลที่มีแนวโน้ม/ไม่ stationary มักได้โมเดล d=0 ที่ AIC ต่ำ
    # หลอกๆ จากการฟิตแบบ ARMA แต่พอพยากรณ์ระยะยาวค่าจะไหลกลับไปหาค่าเฉลี่ยของ
    # อนุกรมทั้งหมดแทนที่จะไปตามแนวโน้มจริง ทำให้ค่าพยากรณ์รูดฮวบผิดปกติ)
    def _select_d(vals, max_diff):
        d = 0
        cur = vals.copy()
        while d < max_diff:
            try:
                pvalue = adfuller(cur, autolag="AIC")[1]
            except Exception:
                break
            if pvalue < 0.05:
                break
            cur = np.diff(cur)
            d += 1
        return d

    fixed_d = _select_d(y, max_d)

    best_aic = np.inf
    best_order = None
    best_fit = None
    for p in range(0, max_p + 1):
        for d in (fixed_d,):
            for q in range(0, max_q + 1):
                if p == 0 and q == 0:
                    continue
                try:
                    fit = ARIMA(y, order=(p, d, q)).fit()
                    if np.isfinite(fit.aic) and fit.aic < best_aic:
                        best_aic = fit.aic
                        best_order = (p, d, q)
                        best_fit = fit
                except Exception:
                    continue

    if best_fit is None:
        # กันเหนียว: ถ้าไม่มีชุด (p,d,q) ไหน fit ได้เลย ใช้ random walk with
        # drift แทน (โมเดลพื้นฐานที่สุด ยังพยากรณ์แนวโน้มต่อได้เสมอ)
        best_fit = ARIMA(y, order=(0, 1, 0), trend="t").fit()
        best_order = (0, 1, 0)

    fc = best_fit.get_forecast(steps=periods)
    summary = fc.summary_frame(alpha=0.05)
    last_year = int(series.index.max())
    future_years = [last_year + i for i in range(1, periods + 1)]
    forecast_df = pd.DataFrame(
        {
            "mean": summary["mean"].values,
            "lower": summary["mean_ci_lower"].values,
            "upper": summary["mean_ci_upper"].values,
        },
        index=future_years,
    )
    return forecast_df, best_order


def _run_backtest(tfp_series: pd.Series, min_train: int = 8, test_years: int = 5):
    """ทดสอบความแม่นยำของแบบจำลองย้อนหลัง (holdout backtest) — ไม่ใช้ทฤษฎีใหม่
    เพิ่มเติมจากที่มีอยู่แล้วเลย แค่เรียก _auto_arima_forecast ตัวเดิมซ้ำ โดย:
    1) ซ่อนข้อมูล `test_years` ปีสุดท้ายไว้ (แสร้งทำเป็นว่ายังไม่รู้อนาคต)
    2) ให้โมเดล ARIMA พยากรณ์ปีที่ซ่อนไว้จากข้อมูลที่เหลือ
    3) เทียบค่าพยากรณ์กับค่าจริงที่รู้อยู่แล้ว ว่าใกล้เคียงกันแค่ไหน
    พร้อมเทียบกับ "Naive forecast" (สมมติว่าปีต่อๆ ไปเท่ากับปีสุดท้ายก่อนซ่อนข้อมูล
    เฉยๆ ไม่ใช้แบบจำลองใดเลย) เป็นเส้นฐานว่า ARIMA พยากรณ์แม่นกว่าการเดาเปล่าๆ แค่ไหน
    คืนค่า (bt_df, metrics, None) หรือ (None, None, ข้อความเหตุผล) ถ้าทำไม่ได้"""
    n = len(tfp_series)
    max_test = n - min_train
    if max_test < 1:
        return None, None, f"ข้อมูลไม่พอสำหรับทดสอบย้อนหลัง (ต้องมีอย่างน้อย {min_train + 1} ปี)"
    test_years = min(test_years, max_test)
    train = tfp_series.iloc[:-test_years]
    test = tfp_series.iloc[-test_years:]
    try:
        bt_forecast_df, bt_order = _auto_arima_forecast(train, test_years)
    except Exception as e:
        return None, None, f"ทดสอบย้อนหลังไม่สำเร็จ: {e}"

    naive_val = float(train.iloc[-1])  # Naive forecast: คงค่าปีสุดท้ายก่อนซ่อนข้อมูลไว้ทุกปีถัดไป
    rows = []
    for yr, actual in test.items():
        arima_pred = float(bt_forecast_df.loc[int(yr), "mean"]) if int(yr) in bt_forecast_df.index else None
        rows.append({"ปี": int(yr), "ค่าจริง": float(actual), "ARIMA": arima_pred, "Naive": naive_val})
    bt_df = pd.DataFrame(rows).set_index("ปี")

    def _mape(actual, pred):
        return float(np.mean(np.abs((actual - pred) / actual)) * 100)

    def _rmse(actual, pred):
        return float(np.sqrt(np.mean((actual - pred) ** 2)))

    metrics = {
        "arima_mape": _mape(bt_df["ค่าจริง"], bt_df["ARIMA"]),
        "arima_rmse": _rmse(bt_df["ค่าจริง"], bt_df["ARIMA"]),
        "naive_mape": _mape(bt_df["ค่าจริง"], bt_df["Naive"]),
        "naive_rmse": _rmse(bt_df["ค่าจริง"], bt_df["Naive"]),
        "order": bt_order,
        "test_years": test_years,
        "train_years": len(train),
    }
    return bt_df, metrics, None

def _nice_line_chart_with_forecast(hist_series: pd.Series, forecast_df: pd.DataFrame,
                                    color: str = "#F97316", forecast_color: str = "#2F6FED",
                                    height: int = 340, display_from_year: int = None):
    """เหมือน _nice_line_chart แต่ต่อเส้นพยากรณ์ (เส้นประสีน้ำเงิน) และแถบ
    ช่วงความเชื่อมั่น 95% (พื้นที่สีน้ำเงินจาง ๆ) ต่อจากข้อมูลจริงให้ในกราฟเดียวกัน

    display_from_year (ใหม่): ถ้าระบุ จะตัดข้อมูลจริงก่อนปีนี้ออกจาก "การแสดงผล
    กราฟ" เท่านั้น (ไม่กระทบข้อมูลที่ใช้ฟิตโมเดล/คำนวณ ARIMA ซึ่งยังใช้ข้อมูลเต็ม
    ทุกปีตามเดิม) ใช้ตอนช่วงข้อมูลยาวมาก (เช่น 68 ปี) จนแกน x แน่น/กราฟรกเกินไป"""
    hist = hist_series.copy()
    hist.index = hist.index.map(int)
    if display_from_year is not None:
        hist = hist[hist.index >= display_from_year]
    years_hist = list(hist.index)
    years_fc = list(forecast_df.index)
    all_years = years_hist + years_fc
    year_order = [str(y) for y in all_years]

    df = pd.DataFrame({"ปี": year_order, "ปี_num": all_years})
    df["ข้อมูลจริง"] = df["ปี_num"].map(hist.to_dict())

    # เชื่อมจุดสุดท้ายของข้อมูลจริงเข้ากับเส้นพยากรณ์ ไม่ให้เส้นขาดตอน
    last_year, last_val = years_hist[-1], float(hist.iloc[-1])
    fc_mean = {last_year: last_val, **forecast_df["mean"].to_dict()}
    fc_lower = {last_year: last_val, **forecast_df["lower"].to_dict()}
    fc_upper = {last_year: last_val, **forecast_df["upper"].to_dict()}
    df["พยากรณ์"] = df["ปี_num"].map(fc_mean)
    df["ขอบล่าง"] = df["ปี_num"].map(fc_lower)
    df["ขอบบน"] = df["ปี_num"].map(fc_upper)

    n = len(df)
    step = max(1, round(n / 12))
    tick_vals = df["ปี"].iloc[::step].tolist()
    if df["ปี"].iloc[-1] not in tick_vals:
        tick_vals.append(df["ปี"].iloc[-1])

    x_enc = alt.X(
        "ปี:O", sort=year_order, title=None,
        axis=alt.Axis(values=tick_vals, labelAngle=0, grid=False,
                       domain=False, tickColor="#E9ECF1",
                       labelColor="#5B6B7C", labelFontSize=11, labelPadding=6),
    )
    y_axis = alt.Axis(grid=True, gridColor="#EEF1F5", gridDash=[3, 3],
                       domain=False, tickColor="#E9ECF1",
                       labelColor="#5B6B7C", labelFontSize=11)

    base = alt.Chart(df)

    ci_band = base.mark_area(opacity=0.15, color=forecast_color).encode(
        x=x_enc, y=alt.Y("ขอบล่าง:Q", title=None, axis=y_axis), y2="ขอบบน:Q",
    )
    hist_area = base.mark_area(
        interpolate="monotone", line=False,
        color=alt.Gradient(
            gradient="linear",
            stops=[alt.GradientStop(color=color, offset=0),
                   alt.GradientStop(color="#FFFFFF", offset=1)],
            x1=1, x2=1, y1=1, y2=0,
        ),
        opacity=0.35,
    ).encode(x=x_enc, y=alt.Y("ข้อมูลจริง:Q", title=None, axis=y_axis))
    hist_line = base.mark_line(
        interpolate="monotone", color=color, strokeWidth=2.6,
        point=alt.OverlayMarkDef(filled=True, size=30, color=color, stroke="#FFFFFF", strokeWidth=1.6),
    ).encode(
        x=x_enc, y=alt.Y("ข้อมูลจริง:Q"),
        tooltip=[alt.Tooltip("ปี:O", title="ปี"),
                 alt.Tooltip("ข้อมูลจริง:Q", title="ค่าจริง", format=".4f")],
    )
    fc_line = base.mark_line(
        interpolate="monotone", color=forecast_color, strokeWidth=2.6, strokeDash=[6, 4],
        point=alt.OverlayMarkDef(filled=True, size=30, color=forecast_color, stroke="#FFFFFF", strokeWidth=1.6),
    ).encode(
        x=x_enc, y=alt.Y("พยากรณ์:Q"),
        tooltip=[alt.Tooltip("ปี:O", title="ปี"),
                 alt.Tooltip("พยากรณ์:Q", title="ค่าพยากรณ์", format=".4f")],
    )
    fc_points = base.mark_point(color=forecast_color, filled=True, size=45).transform_filter(
        alt.datum["ปี_num"] > last_year
    ).encode(x=x_enc, y=alt.Y("พยากรณ์:Q"))

    chart = (
        (ci_band + hist_area + hist_line + fc_line + fc_points)
        .properties(width="container", height=height, padding={"left": 4, "right": 10, "top": 8, "bottom": 4})
        .configure_view(strokeWidth=0)
        .configure_axis(labelFont=FONT_FAMILY, titleFont=FONT_FAMILY)
    )
    st.altair_chart(chart, use_container_width=True)
    # flex-wrap:wrap กัน legend ตกขอบขวาเวลาหน้าจอแคบ (แทนที่จะโดนตัดหาย
    # ก็ให้มันขึ้นบรรทัดใหม่แทน), row-gap เผื่อกรณีตัดบรรทัด
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;justify-content:flex-end;column-gap:18px;row-gap:6px;'
        f'font-size:0.82rem;color:var(--brand-navy-soft);margin-top:-6px;">'
        f'<span style="white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:50%;background:{color};margin-right:5px;"></span>ข้อมูลจริง</span>'
        f'<span style="white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:50%;background:{forecast_color};margin-right:5px;"></span>พยากรณ์ (ARIMA)</span>'
        f'<span style="white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:2px;background:{forecast_color};opacity:0.3;margin-right:5px;"></span>'
        f'ช่วงความเชื่อมั่น 95%</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _compute_influence_df(model_df: pd.DataFrame, dep_ln: str, active_lr_vars: list, lr_raw_map: dict):
    """คำนวณสัดส่วนอิทธิพล (standardized coefficient) ของตัวแปรอิสระแต่ละตัวในสมการ
    ระยะยาว เทียบกันเป็น % (รวมกันได้ 100%) — ดึงตรรกะเดิมออกมาจากหน้า "พยากรณ์ TFP"
    เป็นฟังก์ชันกลาง เพื่อให้หน้า "แดชบอร์ดสำหรับนำเสนอ (สรุปหน้าเดียว)" เรียกใช้ซ้ำได้
    คืนค่า (infl_df, None) เมื่อคำนวณได้ หรือ (None, ข้อความเหตุผล) เมื่อคำนวณไม่ได้"""
    influence_vars = [
        v for v in active_lr_vars
        if v != "const" and v in lr_raw_map and v in model_df.columns
    ]
    if len(influence_vars) < 2:
        return None, "ต้องมีตัวแปรอิสระอย่างน้อย 2 ตัวในสมการระยะยาว จึงจะเทียบสัดส่วนอิทธิพลกันได้"
    sample_df = model_df[[dep_ln] + influence_vars].dropna()
    y_std = sample_df[dep_ln].std() if not sample_df.empty else None
    if sample_df.empty or len(sample_df) < 3 or not y_std or pd.isna(y_std):
        return None, "ข้อมูลไม่พอสำหรับคำนวณสัดส่วนอิทธิพล (ต้องการอย่างน้อย 3 ปีที่มีข้อมูลครบทุกตัวแปร)"
    rows = []
    for v in influence_vars:
        x_std = sample_df[v].std()
        if not x_std or pd.isna(x_std) or x_std == 0:
            continue
        std_beta = lr_raw_map[v]["coef"] * (x_std / y_std)
        rows.append({"code": v, "label": _var_full_name(v), "std_beta": std_beta})
    if not rows:
        return None, "ไม่สามารถคำนวณสัดส่วนอิทธิพลได้ (ส่วนเบี่ยงเบนมาตรฐานของตัวแปรบางตัวเป็น 0)"
    infl_df = pd.DataFrame(rows)
    infl_df["abs_beta"] = infl_df["std_beta"].abs()
    total_abs = infl_df["abs_beta"].sum()
    infl_df["สัดส่วน (%)"] = infl_df["abs_beta"] / total_abs * 100
    infl_df["ทิศทาง"] = infl_df["std_beta"].apply(
        lambda x: "หนุนเสริม TFP (+)" if x >= 0 else "ฉุดรั้ง TFP (−)"
    )
    infl_df = infl_df.sort_values("สัดส่วน (%)", ascending=False).reset_index(drop=True)
    return infl_df, None


if st.session_state.page == "home":
    if not st.session_state.research_authenticated:
        # หน้าล็อกอิน — แสดงแทนเนื้อหาบทสรุปสำหรับนำเสนอจนกว่าจะกรอก user/password ถูกต้อง
        st.markdown(
            f'<div class="section-card" style="max-width:420px;margin:40px auto;'
            f'text-align:center;">'
            f'<div class="section-title" style="justify-content:center;align-items:center;">'
            f'<div class="section-num" style="position:relative;top:-3px;margin-top:0;">🔒</div>'
            f'<div class="section-title-text"><h3>สำหรับคณะวิจัยเท่านั้น</h3></div></div>'
            f'<p style="color:var(--brand-navy-soft);font-size:0.9rem;margin-top:-6px;">'
            f'กรุณาเข้าสู่ระบบด้วยบัญชีคณะวิจัยเพื่อดูหน้านี้</p></div>',
            unsafe_allow_html=True,
        )
        _login_col = st.columns([1, 1.4, 1])[1]
        with _login_col:
            if _research_login_config_error:
                st.error(_research_login_config_error)
            else:
                # พื้นหลังกรอบฟอร์มล็อกอินเป็นสีขาว (เดิมกลืนไปกับพื้นหลังหน้าเว็บสีครีม)
                # ส่วนช่องกรอกข้อความ (input) ยังคงเป็นสีเทาอ่อนตามเดิม
                st.markdown(
                    """
                    <style>
                    div[data-testid="stForm"] {
                        background: #FFFFFF !important;
                        border-radius: 14px;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                with st.form("research_login_form", clear_on_submit=False):
                    login_user = st.text_input("ชื่อผู้ใช้ (Username)")
                    login_pass = st.text_input("รหัสผ่าน (Password)", type="password")
                    login_submitted = st.form_submit_button("เข้าสู่ระบบ", use_container_width=True)
                if login_submitted:
                    # ใช้ hmac.compare_digest แทน == ธรรมดา เพื่อลดความเสี่ยงจาก
                    # timing attack (เดารหัสผ่านจากเวลาที่ใช้เทียบสตริง)
                    user_ok = hmac.compare_digest(
                        login_user.encode("utf-8"), RESEARCH_USERNAME.encode("utf-8")
                    )
                    pass_ok = hmac.compare_digest(
                        login_pass.encode("utf-8"), RESEARCH_PASSWORD.encode("utf-8")
                    )
                    if user_ok and pass_ok:
                        st.session_state.research_authenticated = True
                        st.rerun()
                    else:
                        st.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        st.stop()

    # ------------------------------------------------------------------------------
    # หัวเพจ (header) — ชื่อรายงาน + สถานะไฟล์ที่อัปโหลด + ป้ายผู้ใช้งาน
    # ------------------------------------------------------------------------------
    header_right = (
        f'<div class="header-chip">{icon("database", 14, 1.5)}<span>TFP-Data — อัปเดตล่าสุด '
        f'{st.session_state.gsheet_loaded_at.strftime("%d/%m/%Y %H:%M")}</span></div>'
        if "gsheet_raw_df" in st.session_state else
        f'<div class="header-chip">{icon("file", 14, 1.5)}<span>ยังไม่ได้ดึงข้อมูล</span></div>'
    )
    st.markdown(
        f"""
        <div class="app-header">
            <div>
                <h1>ระบบวิเคราะห์ผลิตภาพปัจจัยการผลิตรวมมหภาคด้วยแบบจำลองเศรษฐมิติ</h1>
                <p class="app-header-desc">และสร้างรายงานสรุปผลสำหรับนำเสนอด้วยปัญญาประดิษฐ์เพื่อสนับสนุนการติดตามผลและประเมินผลนโยบายด้านวิทยาศาสตร์ วิจัย และนวัตกรรม (ววน.) ของสอวช.</p>
                <p class="app-header-desc" style="margin-top:4px;"><strong>ขอบเขต:</strong> ระบบนี้วิเคราะห์เฉพาะ<strong>ระดับเศรษฐกิจมหภาค (Macro Level)</strong> ด้วยแบบจำลอง Error-Correction Model (ECM) เท่านั้น</p>
            </div>
        </div>
        <div style="display:flex; justify-content:flex-end; margin-bottom:10px;">
            {header_right}
        </div>
        """,
        unsafe_allow_html=True,
    )


    def metric_card(bg, icon, value, label):
        return (
            f'<div class="metric-card"><div class="metric-icon" style="background:{bg};">{icon}</div>'
            f'<div><div class="metric-value">{value}</div><div class="metric-label">{label}</div></div></div>'
        )


    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(metric_card("var(--green)", icon("check", 21, 2), n_pass if result_ready else "-", "ผ่านเกณฑ์"), unsafe_allow_html=True)
    with m2:
        st.markdown(metric_card("var(--amber)", icon("alert", 21, 1.6), n_watch if result_ready else "-", "พิจารณาเพิ่มเติม"), unsafe_allow_html=True)
    with m3:
        st.markdown(metric_card("var(--red)", icon("x", 21, 2), n_fail if result_ready else "-", "ไม่ผ่านเกณฑ์"), unsafe_allow_html=True)
    with m4:
        r2_display = f"{adj_r2_lr:.4f}" if adj_r2_lr is not None else "-"
        st.markdown(metric_card("var(--blue)", icon("trend-up", 21, 1.8), r2_display, "Adj. R² ระยะยาว"), unsafe_allow_html=True)
    with m5:
        r2_sr_display = f"{adj_r2_sr:.4f}" if adj_r2_sr is not None else "-"
        st.markdown(metric_card("var(--blue)", icon("trend-down", 21, 1.8), r2_sr_display, "Adj. R² ระยะสั้น"), unsafe_allow_html=True)

    st.write("")

    if not result_ready:
        st.info("คลิกเพื่อดึงข้อมูลอัตโนมัติจากแถบด้านซ้ายเพื่อเริ่มต้นการวิเคราะห์")
    else:
        if vars_customized:
            st.info(
                "ℹ️ ผลลัพธ์ด้านล่างนี้รันด้วย **ชุดตัวแปรที่คณะวิจัยปรับไว้** ไม่ใช่ค่า default ในไฟล์โค้ด "
                "— ดูรายละเอียดและเหตุผลได้ที่ประวัติการปรับตัวแปรด้านล่าง"
            )

        # ================= การ์ดตัวแปรในสมการ (ระยะสั้น / ระยะยาว) แบบย่อ — ย้ายมา
        # จากหน้า Dashboard เดิม มาไว้เป็นภาพรวมสั้น ๆ ก่อนตารางละเอียดในหมวด 1 ด้านล่าง =================
        def _mini_var_table_card(raw_map: dict, title_th: str, badge_text: str, accent_num: str):
            rows = [(base, info) for base, info in raw_map.items() if base != "const"]
            # เรียงตามลำดับมาตรฐานของตัวแปร (VARIABLE_ORDER) เท่าที่มีอยู่จริงในสมการนี้
            order_index = {code: i for i, code in enumerate(VARIABLE_ORDER)}
            rows.sort(key=lambda kv: order_index.get(kv[0], 999))
            body_html = ""
            for base, info in rows:
                coef = info.get("coef")
                p_val = info.get("p")
                label = _var_full_name(base) if base in VARIABLE_LABELS else base
                coef_text = f"{coef:.3f}" if coef is not None else "-"
                p_text = f"{p_val:.3f}" if p_val is not None else "-"
                is_up = (coef or 0) >= 0
                dir_html = (
                    f'<span class="nxpo-var-dir up">{icon("trend-up", 15, 2)}</span>' if is_up
                    else f'<span class="nxpo-var-dir down">{icon("trend-down", 15, 2)}</span>'
                )
                body_html += (
                    f"<tr><td>{label}</td><td>{coef_text}</td><td>{p_text}</td><td>{dir_html}</td></tr>"
                )
            st.markdown(
                f'<div class="section-card"><div class="nxpo-var-card-head">'
                f'<div class="title-group"><div class="section-num">{accent_num}</div>'
                f'<div class="section-title-text"><h3>ตัวแปรในสมการ <span style="white-space:nowrap;">({title_th})</span></h3></div></div>'
                f'<span class="nxpo-run-badge">{badge_text}</span></div>'
                f'<table class="nxpo-var-table"><thead><tr>'
                f'<th>ตัวแปร</th><th>ค่าสัมประสิทธิ์</th><th>p-value</th><th>ทิศทาง</th>'
                f'</tr></thead><tbody>{body_html}</tbody></table>'
                f'</div>',
                unsafe_allow_html=True,
            )

        var_col_sr, var_col_lr = st.columns(2)
        with var_col_sr:
            if sr_raw_map:
                _mini_var_table_card(sr_raw_map, "ระยะสั้น", "Short Run", icon("clock", 20, 2))
            else:
                st.info("ยังไม่มีตัวแปรในสมการระยะสั้น")
        with var_col_lr:
            if lr_raw_map:
                _mini_var_table_card(lr_raw_map, "ระยะยาว", "Long Run", icon("bars", 20, 2))
            else:
                st.info("ยังไม่มีตัวแปรในสมการระยะยาว")
        st.caption("รายละเอียดตัวแปรครบทุกตัวพร้อมระดับนัยสำคัญ ดูได้ในตารางค่าสัมประสิทธิ์ด้านล่าง (หมวด 1)")
        st.write("")

        # ================= หมวด 1: ผลการทดสอบปัจจัย ววน. =================
        st.markdown(
            '<div class="section-card"><div class="section-title">'
            '<div class="section-num">1</div>'
            '<div class="section-title-text"><h3>ผลการทดสอบปัจจัยด้านวิทยาศาสตร์ วิจัย และนวัตกรรม (ววน.) '
            'ที่มีต่อผลิตภาพทางเศรษฐกิจไทย</h3></div>'
            '</div>',
            unsafe_allow_html=True,
        )
        def _style_coef_cell(value) -> str:
            """ใส่สีให้ตัวเลขสัมประสิทธิ์ตามระดับนัยสำคัญทางสถิติ (ดาว ***/**/*)
            เพื่อให้อ่านตารางง่ายขึ้นด้วยสายตา ไม่ต้องไล่หาดาวทีละช่อง"""
            s = str(value)
            if s in ("-", "nan", "None", ""):
                return '<span style="color:#B9C0CB;">-</span>'
            if "***" in s:
                return f'<span style="color:var(--green);font-weight:700;">{s}</span>'
            if "**" in s:
                return f'<span style="color:var(--brand-orange-dark);font-weight:700;">{s}</span>'
            if "*" in s:
                return f'<span style="color:var(--amber);font-weight:600;">{s}</span>'
            return s

        combined_header_html = "".join(f"<th>{c}</th>" for c in combined_table.columns)
        combined_rows_html = "".join(
            "<tr>" + "".join(
                f'<td style="font-weight:600;color:var(--brand-navy);">{v}</td>'
                if i == 0 else f"<td>{_style_coef_cell(v)}</td>"
                for i, v in enumerate(row)
            ) + "</tr>"
            for row in combined_table.values.tolist()
        )
        st.markdown(
            f'<div style="overflow-x:auto;"><table class="tfp-table tfp-table-left"><thead><tr>'
            f'{combined_header_html}</tr></thead><tbody>{combined_rows_html}</tbody></table></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"Adj. R² (สมการระยะยาว) = {adj_r2_lr:.4f}  |  Adj. R² (สมการระยะสั้น) = {adj_r2_sr:.4f}"
        )
        st.caption(
            'หมายเหตุ: ***, **, * หมายถึง นัยสำคัญทางสถิติที่ระดับความเชื่อมั่น 99%, 95%, 90% '
            'ตามลำดับ | "-" หมายถึงตัวแปรที่ไม่ได้อยู่ในสมการนี้ | Δ และ Δ² หมายถึงผลต่างลำดับที่ 1 '
            'และ 2 ตามลำดับ'
        )
        st.download_button(
            "⬇️ ดาวน์โหลดตาราง (.csv)",
            data=combined_table.to_csv(index=False).encode("utf-8-sig"),
            file_name="ตาราง_ววน.csv",
            mime="text/csv",
            key="dl_combined_table",
        )
        st.markdown('</div>', unsafe_allow_html=True)

        # ================= หมวด 2: ตรวจสอบข้อสมมติฐาน (Diagnostics) =================
        st.markdown(
            '<div class="section-card"><div class="section-title">'
            '<div class="section-num">2</div>'
            '<div class="section-title-text"><h3>ตรวจสอบข้อสมมติฐานของแบบจำลอง (Diagnostics)</h3>'
            '</div></div>',
            unsafe_allow_html=True,
        )
        st.warning(
            "⚠️ **คำแนะนำในการอ่านผล**: ตารางนี้ใช้สำหรับ**ตรวจสอบและแจ้งเตือนเบื้องต้น** "
            "เพื่อช่วยผู้วิจัยพิจารณาผลการทดสอบทางเศรษฐมิติเท่านั้น ไม่ควรใช้สีหรือสถานะในตาราง"
            "เป็นเกณฑ์ในการสรุปผลโดยตรง\n\n"
            "เกณฑ์ที่แสดง เช่น VIF > 10 หรือ p-value < 0.05 เป็นเพียงเกณฑ์ทั่วไปสำหรับการประเมินเบื้องต้น "
            "การพิจารณาผลควรคำนึงถึงวัตถุประสงค์ของการทดสอบ สมมติฐานทางสถิติ และบริบทของแบบจำลองร่วมด้วย "
            "โดยอ่านรายละเอียดในคอลัมน์ **หมายเหตุ** ประกอบทุกครั้ง ก่อนนำผลไปใช้ในการวิเคราะห์หรือจัดทำรายงาน"
        )
        if diag_table_display is not None:
            def _status_badge(s):
                if s.startswith("🟢"):
                    return '<span class="badge-pill badge-pass">🟢 ผ่าน</span>'
                if s.startswith("🟡"):
                    return '<span class="badge-pill badge-watch">🟡 พิจารณาเพิ่มเติม</span>'
                return '<span class="badge-pill badge-fail">🔴 ไม่ผ่าน</span>'

            def _wrap_short_long_run(v):
                """ป้ายเช่น 'Stationarity (Short-run)' ตอนคอลัมน์แคบจะตัดคำกลางคำ
                'Short-'/'run)' เพราะเบราว์เซอร์ตัดตรง '-' ได้ — แทรก <br> ก่อนวงเล็บ
                ให้ '(Short-run)'/'(Long-run)' ทั้งก้อนตกบรรทัดใหม่แทน (ใช้แค่ตอนแสดงผล
                ในตาราง HTML นี้เท่านั้น ไม่กระทบไฟล์ CSV ที่ดาวน์โหลด)"""
                s = str(v)
                s = s.replace(" (Short-run)", "<br>(Short-run)")
                s = s.replace(" (Long-run)", "<br>(Long-run)")
                return s

            rows_html = "".join(
                "<tr>" + "".join(
                    f"<td>{_status_badge(v) if col == 'สถานะ' else _wrap_short_long_run(v)}</td>"
                    for col, v in zip(diag_table_display.columns, row)
                ) + "</tr>"
                for row in diag_table_display.values.tolist()
            )
            header_html = "".join(f"<th>{c}</th>" for c in diag_table_display.columns)
            st.markdown(
                f'<div style="overflow-x:auto;"><table class="tfp-table"><thead><tr>{header_html}</tr></thead>'
                f'<tbody>{rows_html}</tbody></table></div>',
                unsafe_allow_html=True,
            )
            if n_fail:
                st.caption(f"🔴 มี {n_fail} รายการที่ไม่ผ่านเกณฑ์ทั่วไป และ 🟡 {n_watch} รายการที่ก้ำกึ่ง/ต้องพิจารณาเพิ่มเติม")
            elif n_watch:
                st.caption(f"🟡 มี {n_watch} รายการที่ก้ำกึ่ง/ต้องพิจารณาเพิ่มเติม — ไม่มีรายการที่ไม่ผ่านชัดเจน")
            else:
                st.caption("🟢 ทุกรายการผ่านเกณฑ์ทั่วไปเบื้องต้น")
            st.download_button(
                "⬇️ ดาวน์โหลดตาราง Diagnostics (.csv)",
                data=diag_table_display.to_csv(index=False).encode("utf-8-sig"),
                file_name="diagnostics_TFP.csv",
                mime="text/csv",
                key="dl_diag_table",
            )
        st.markdown('</div>', unsafe_allow_html=True)

        # ================= หมวด 3: ปรับตัวแปรในสมการ (สำหรับงานวิจัย) =================
        st.markdown(
            '<div class="section-card"><div class="section-title">'
            '<div class="section-num">3</div>'
            '<div class="section-title-text"><h3>ปรับตัวแปรในสมการ (สำหรับงานวิจัย)</h3>'
            '</div></div>',
            unsafe_allow_html=True,
        )
        # กรอบ expander นี้เดิมพื้นหลังใส (โปร่งเห็นสีครีมของพื้นหลังหน้าเว็บทะลุออกมา)
        # ทำให้ดูกลืนไปกับพื้นหลัง — ใส่พื้นขาวให้ชัดเจนว่าเป็นกล่องเนื้อหาแยกต่างหาก
        st.markdown(
            """
            <style>
            .st-key-adjust_vars_expander {
                background: #FFFFFF !important;
                border-radius: 12px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("🛠️ กดเพื่อปรับตัวแปรในสมการ (สำหรับคณะวิจัย)", expanded=False,
                          key="adjust_vars_expander"):
            st.caption(
                "ใช้ส่วนนี้เมื่อพิจารณาจากตาราง Diagnostics ด้านบนแล้วเห็นว่าควรตัด/เพิ่มตัวแปร "
                "กลับเข้าสมการ (เช่น VIF สูงเกินไป) การปรับที่นี่จะไม่แก้ไขไฟล์ TFP.py — มีผลเฉพาะ "
                "รอบการใช้งานนี้เท่านั้น และทุกครั้งที่ปรับจะถูกบันทึกไว้ในประวัติด้านล่างพร้อมเหตุผล"
            )

            all_lr_vars = list(LONG_RUN_VARS)
            new_lr_vars = st.multiselect(
                "ตัวแปรในสมการระยะยาว (Long-run)",
                options=all_lr_vars,
                default=active_lr_vars,
                format_func=var_label_with_abbr,
                key="ms_lr_vars",
            )

            all_sr_bases = [c for c, _, _ in SHORT_RUN_SPEC]
            new_sr_bases = st.multiselect(
                "ตัวแปรในสมการระยะสั้น (Short-run ECM)",
                options=all_sr_bases,
                default=active_sr_bases,
                format_func=var_label_with_abbr,
                key="ms_sr_vars",
            )

            reason = st.text_area(
                "เหตุผลของการปรับ (จำเป็นต้องกรอกก่อนยืนยัน)",
                placeholder='เช่น "ln_HDI มี VIF=68.5 สูงเกินเกณฑ์ และมีสหสัมพันธ์กับ MKTCOM สูงถึง 0.991 '
                            'คณะวิจัยจึงมีมติให้ตัด ln_HDI ออกจากสมการระยะยาว"',
                key="var_change_reason",
            )

            removed_lr = sorted(set(active_lr_vars) - set(new_lr_vars))
            added_lr = sorted(set(new_lr_vars) - set(active_lr_vars))
            removed_sr = sorted(set(active_sr_bases) - set(new_sr_bases))
            added_sr = sorted(set(new_sr_bases) - set(active_sr_bases))
            has_change = bool(removed_lr or added_lr or removed_sr or added_sr)

            if has_change:
                change_parts = []
                if removed_lr:
                    change_parts.append(f"ตัดออก (ระยะยาว): {', '.join(var_label_with_abbr(v) for v in removed_lr)}")
                if removed_sr:
                    change_parts.append(f"ตัดออก (ระยะสั้น): {', '.join(var_label_with_abbr(v) for v in removed_sr)}")
                if added_lr:
                    change_parts.append(f"เพิ่มกลับ (ระยะยาว): {', '.join(var_label_with_abbr(v) for v in added_lr)}")
                if added_sr:
                    change_parts.append(f"เพิ่มกลับ (ระยะสั้น): {', '.join(var_label_with_abbr(v) for v in added_sr)}")
                st.info("การเปลี่ยนแปลงที่จะเกิดขึ้นถ้ายืนยัน: " + " | ".join(change_parts))

                CONFIRM_PHRASE = "ยืนยันการปรับตัวแปร"
                confirm_text = st.text_input(
                    f'พิมพ์คำว่า "{CONFIRM_PHRASE}" ให้ตรงเป๊ะเพื่อยืนยัน (ป้องกันการกดพลาด)',
                    key="confirm_phrase_input",
                )
                reason_ok = reason.strip() != ""
                confirm_ok = confirm_text.strip() == CONFIRM_PHRASE
                if not reason_ok:
                    st.caption("⚠️ ต้องกรอกเหตุผลก่อนจึงจะยืนยันได้")
                if confirm_text and not confirm_ok:
                    st.caption("⚠️ ข้อความยืนยันไม่ตรงกับที่กำหนด กรุณาพิมพ์ให้ตรงเป๊ะ")

                if st.button("✅ ยืนยันและรันโมเดลใหม่ด้วยตัวแปรชุดนี้",
                              disabled=not (reason_ok and confirm_ok)):
                    st.session_state.var_audit_log.append({
                        "เวลา": thai_timestamp(),
                        "ตัดออก (ระยะยาว)": ", ".join(removed_lr) or "-",
                        "ตัดออก (ระยะสั้น)": ", ".join(removed_sr) or "-",
                        "เพิ่มกลับ (ระยะยาว)": ", ".join(added_lr) or "-",
                        "เพิ่มกลับ (ระยะสั้น)": ", ".join(added_sr) or "-",
                        "เหตุผล": reason.strip(),
                    })
                    st.session_state.active_long_run_vars = new_lr_vars
                    st.session_state.active_short_run_spec = [
                        spec for spec in SHORT_RUN_SPEC if spec[0] in new_sr_bases
                    ]
                    st.success("บันทึกและปรับตัวแปรแล้ว กำลังรันโมเดลใหม่...")
                    st.rerun()
            else:
                st.caption("ยังไม่มีการเปลี่ยนแปลงจากชุดตัวแปรที่ใช้อยู่ในขณะนี้")

            if active_lr_vars != list(LONG_RUN_VARS) or active_sr_bases != default_sr_bases:
                if st.button("↩️ คืนค่าเริ่มต้นทั้งหมด (ตามที่กำหนดในโค้ด TFP.py)"):
                    st.session_state.active_long_run_vars = list(LONG_RUN_VARS)
                    st.session_state.active_short_run_spec = list(SHORT_RUN_SPEC)
                    st.rerun()

            if st.session_state.var_audit_log:
                st.markdown("**ประวัติการปรับตัวแปร (Audit log)**")
                audit_df = pd.DataFrame(st.session_state.var_audit_log)
                st.dataframe(audit_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "📥 ดาวน์โหลดประวัติการปรับตัวแปร (.csv)",
                    data=audit_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="audit_log_ตัวแปรโมเดล.csv",
                    mime="text/csv",
                )
        st.markdown('</div>', unsafe_allow_html=True)

        # ================= หมวด 4: สร้าง Executive Summary ด้วย AI =================
        # การ์ดนี้ถูกครอบด้วย st.container(key="ai_cta_card") เพื่อให้ CSS
        # ".st-key-ai_cta_card ..." ด้านบน (ธีมกรมท่าเข้ม+ขอบทอง แบบ Exclusive)
        # จับกลุ่มทั้งข้อความและปุ่มด้านล่างเป็นการ์ดเดียวกัน — ห้ามแยก markdown
        # กับ button ออกจาก with-block นี้ ไม่งั้นปุ่มจะหลุดสไตล์กลับไปเป็นปุ่ม
        # primary สีส้มทึบแบบทั่วไปของแอป
        with st.container(key="ai_cta_card"):
            st.markdown(
                '<div class="ai-cta-eyebrow">' + icon("sparkle", 13, 1.8) +
                'AI ANALYSIS · PRESENTATION SUMMARY</div>'
                '<div class="ai-cta-card-inner">'
                '<h3>สร้างรายงานสรุปและสไลด์นำเสนออัตโนมัติด้วยปัญญาประดิษฐ์</h3>'
                '<p>สรุปผลการวิเคราะห์ พร้อมข้อเสนอแนะเชิงนโยบายอย่างชัดเจน '
                'ดาวน์โหลดได้ทั้ง Word และ PPTX</p></div>',
                unsafe_allow_html=True,
            )
            gen_summary_clicked = st.button(
                "✦  กดเพื่อสร้างรายงานสรุปอัตโนมัติด้วย AI", type="primary", key="ai_cta_button",
            )
        if gen_summary_clicked:
            with st.spinner("กำลังสรุปผลอัตโนมัติ..."):
                try:
                    summary_text = generate_summary_gemini(lr_res, sr_res, model_df, dep_ln)
                    # กันเหนียว: ตัดบรรทัดตาราง markdown (ขึ้นต้นด้วย |) ที่ Gemini อาจ
                    # แอบใส่มาแม้จะสั่งห้ามแล้วใน SYSTEM_PROMPT เพราะตารางจริงแสดงแยกไว้
                    # ด้านบนแล้ว ไม่ต้องการให้ซ้ำ/โชว์รหัสตัวแปรดิบอีกรอบ (เว้นบรรทัดว่างไว้
                    # ตามเดิม ไม่ตัดออก เพื่อไม่ให้ย่อหน้าติดกัน)
                    def _is_markdown_table_row(line: str) -> bool:
                        s = line.strip()
                        if not s:
                            return False
                        return s.startswith("|") or set(s) <= set("|-: ")

                    summary_text = "\n".join(
                        line for line in summary_text.split("\n")
                        if not _is_markdown_table_row(line)
                    )
                    st.markdown(_web_summary_text(summary_text))
                    footer = (f"*จัดทำโดยระบบปัญญาประดิษฐ์ Google Gemini "
                              f"({GEMINI_MODEL}) — สร้างเมื่อวันที่ {thai_timestamp()}*")
                    st.markdown("---")
                    st.caption(footer)

                    full_output = summary_text + "\n\n---\n" + footer
                    word_bytes = build_word_report(
                        summary_text, lr_table, sr_table,
                        summary_adj_r2(lr_res), summary_adj_r2(sr_res), model_df,
                    )

                    pptx_bytes = build_pptx_report(
                        summary_text, lr_table, sr_table,
                        summary_adj_r2(lr_res), summary_adj_r2(sr_res), model_df,
                    )

                    dl_col1, dl_col2, dl_col3 = st.columns(3)
                    with dl_col1:
                        st.download_button(
                            "📄 ดาวน์โหลดสรุปเป็น Word (มีโลโก้ แก้ไขได้)",
                            data=word_bytes,
                            file_name="สรุปสำหรับนำเสนอ_TFP.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                    with dl_col2:
                        st.download_button(
                            "ดาวน์โหลดสไลด์นำเสนอ (.pptx)",
                            data=pptx_bytes,
                            file_name="สไลด์นำเสนอ_TFP.pptx",
                            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        )
                    with dl_col3:
                        st.download_button(
                            "ดาวน์โหลดสรุปเป็น .txt",
                            data=full_output,
                            file_name="summary_for_presentation.txt",
                        )
                except Exception as e:
                    st.error(f"เรียก Gemini ไม่สำเร็จ: {e}")

# ------------------------------------------------------------------------------
# หน้า "Dashboard พยากรณ์ TFP" — หน้าเดียวครบทั้งภาพรวมและมุมมองเต็ม/โต้ตอบได้:
# กราฟพยากรณ์ ARIMA พร้อมแถบ KPI + slider เลือกช่วงปี, กราฟแนวโน้มรายตัวแปร,
# เครื่องมือจำลองสถานการณ์ (what-if) และกราฟสัดส่วนอิทธิพลของแต่ละตัวแปร
# (เดิมแยกเป็นหน้า "Dashboard" สรุปสั้น ๆ ตายตัว 5 ปี กับหน้า "พยากรณ์ TFP" แบบเต็ม
# คนละหน้า ทำให้ผู้ใช้งงว่าต้องดูหน้าไหน — รวมเป็นหน้าเดียวแล้ว ยังคง page key เดิม
# คือ "forecast" ไว้ เพื่อไม่กระทบปุ่ม/ลิงก์อื่นที่อ้างถึงอยู่)
# ------------------------------------------------------------------------------
elif st.session_state.page == "forecast":
    if not result_ready:
        # ----- หน้าแรกที่ผู้ใช้งานเจอตอนเข้าเว็บ (ยังไม่ได้ดึงข้อมูล) -----
        # ออกแบบแยกจากหน้า Dashboard หลังดึงข้อมูลโดยเจตนา ให้เป็นหน้าต้อนรับที่ดูดี
        # เรียบหรู น่าใช้งาน (ไม่ใช้ topbar+info แบบเดิมที่ดูโล่งเกินไป) โดยใช้
        # nxpo-hero ที่มี CSS เตรียมไว้ในไฟล์อยู่แล้ว — พอดึงข้อมูลสำเร็จแล้วหน้านี้
        # จะสลับกลับไปเป็น topbar + Dashboard เต็มรูปแบบตามปกติ (ดูเงื่อนไข else ด้านล่าง)
        st.markdown(
            f'<div class="nxpo-hero" style="{hero_bg_style}"><div class="nxpo-hero-flex">'
            '<div class="nxpo-hero-left" style="flex:1 1 58%;max-width:58%;">'
            '<span class="nxpo-hero-badge-eyebrow">NXPO Data Center • Econometric Analytics</span>'
            '<h1>ระบบวิเคราะห์และพยากรณ์<br>ผลิตภาพปัจจัยการผลิตรวม (TFP)</h1>'
            '<p class="desc">วิเคราะห์แนวโน้มผลิตภาพของประเทศไทยด้วยแบบจำลองเศรษฐมิติ<br>'
            'พร้อมระบบพยากรณ์และสรุปผลอัตโนมัติ</p>'
            f'<div class="cta-hint">{icon("arrow-right", 14, 2)} เริ่มต้นการวิเคราะห์ข้อมูลได้จากเมนูด้านซ้าย</div>'
            '<div class="nxpo-hero-chips">'
            f'<span class="nxpo-hero-chip">{icon("search", 14, 2)} วิเคราะห์ข้อมูล</span>'
            f'<span class="nxpo-hero-chip">{icon("trend-up", 14, 2)} พยากรณ์ TFP</span>'
            f'<span class="nxpo-hero-chip">{icon("check", 14, 2)} ตรวจสอบแบบจำลอง</span>'
            f'<span class="nxpo-hero-chip">{icon("sparkle", 14, 2)} สรุปผลอัตโนมัติ</span>'
            '</div>'
            '</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )
        _welcome_steps = [
            ("database", "ดึงข้อมูลอัตโนมัติ", "กดปุ่ม \"คลิกดึงข้อมูลอัตโนมัติ\" ที่แถบเมนูด้านซ้ายมือ"),
            ("sparkle", "ระบบรันโมเดลให้อัตโนมัติ", "ระบบจะเลือกโมเดล ARIMA ที่เหมาะสม"),
            ("trend-up", "ดูผลพยากรณ์ที่นี่", "กราฟแสดงแนวโน้ม TFP และตัวแปรในสมการ"),
        ]
        _welcome_cols = st.columns(3)
        for _wcol, (ic, title, desc) in zip(_welcome_cols, _welcome_steps):
            with _wcol:
                st.markdown(
                    '<div class="nxpo-control-card" style="text-align:center;">'
                    f'<div style="width:42px;height:42px;border-radius:12px;margin:0 auto 12px;'
                    f'background-image:linear-gradient(155deg,var(--brand-orange),var(--brand-orange-dark));'
                    f'color:#fff;display:flex;align-items:center;justify-content:center;'
                    f'box-shadow:0 5px 12px rgba(217,109,15,0.3);">{icon(ic, 20, 2)}</div>'
                    f'<div style="font-family:var(--font-elegant);font-weight:600;font-size:1rem;'
                    f'color:var(--brand-navy);margin-bottom:4px;">{title}</div>'
                    f'<div style="font-size:0.85rem;color:var(--brand-navy-soft);line-height:1.55;">{desc}</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.markdown(
            f'<div class="nxpo-topbar"><div class="nxpo-topbar-left">'
            f'<div class="nxpo-topbar-logo">{icon("trend-up", 22, 2)}</div>'
            f'<div class="nxpo-topbar-title"><h2>Dashboard พยากรณ์ TFP</h2>'
            f'<span class="eyebrow">TFP Forecast Dashboard</span></div></div></div>',
            unsafe_allow_html=True,
        )
        # ================= กราฟภาพรวม: แนวโน้มดัชนี TFP ย้อนหลัง + พยากรณ์ (ARIMA) =================
        st.markdown(
            f'<div class="section-card"><div class="section-title">'
            f'<div class="section-num">{icon("trend-up", 20, 2)}</div>'
            f'<div class="section-title-text"><h3>แนวโน้มดัชนีผลิตภาพการผลิตรวม (TFP) ย้อนหลัง พร้อมพยากรณ์ล่วงหน้า (ARIMA)</h3>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        tfp_series = model_df[DEP_VAR].dropna().sort_index()
        if tfp_series.empty:
            st.info("ไม่พบข้อมูล TFP ในชุดข้อมูลที่ดึงมา")
        else:
            MIN_POINTS_FOR_ARIMA = 8  # จำนวนปีขั้นต่ำที่พอจะ fit ARIMA ได้อย่างมีความหมาย

            def _kpi_strip_item(bg, icon_svg, value, label):
                return (
                    f'<div class="kpi-strip-item"><div class="metric-icon" style="background:{bg};">{icon_svg}</div>'
                    f'<div><div class="metric-value">{value}</div><div class="metric-label">{label}</div></div></div>'
                )

            def _dash_kpi_card(bg, icon_svg, value, label):
                # ยังใช้แบบกล่องเดี่ยว (มีขอบ/เงาของตัวเอง) สำหรับจุดอื่นที่ไม่ได้
                # อยู่ใน .kpi-strip เช่นการ์ดเทียบผลใน Backtesting ด้านล่าง
                return (
                    f'<div class="metric-card"><div class="metric-icon" style="background:{bg};">{icon_svg}</div>'
                    f'<div><div class="metric-value">{value}</div><div class="metric-label">{label}</div></div></div>'
                )

            _arima_forecast_available = False
            if len(tfp_series) >= MIN_POINTS_FOR_ARIMA:
                # ----- เลือกช่วงพยากรณ์ล่วงหน้า -----
                # เปลี่ยนจากแถบเลื่อนอิสระ (1-30 ปี) เป็นดรอปดาวน์ตัวเลือกที่กำหนด
                # ไว้ล่วงหน้า (3/5/10/15 ปี) ตามที่ขอ พร้อมแสดงช่วงปีจริงในตัวเลือก
                # เลย (เช่น "2023–2027 (5 ปี)") ให้เห็นภาพทันทีว่าพยากรณ์ถึงปีไหน
                _last_data_year = int(tfp_series.index.max())
                horizon = st.selectbox(
                    "จำนวนปีที่ต้องการพยากรณ์ล่วงหน้า",
                    options=[3, 5, 10, 15],
                    index=1,
                    format_func=lambda n: f"{_last_data_year + 1}–{_last_data_year + n} ({n} ปี)",
                    key="tfp_forecast_horizon",
                    help="เลือกช่วงเวลาที่ต้องการพยากรณ์ล่วงหน้า ยิ่งพยากรณ์ไกลจากข้อมูลจริง "
                         "ยิ่งมีความไม่แน่นอนสูงขึ้น (ช่วงความเชื่อมั่นจะกว้างขึ้นตามไปด้วย)",
                )

                with st.spinner("กำลังหาโมเดล ARIMA ที่เหมาะสมและพยากรณ์..."):
                    forecast_df, arima_order = _auto_arima_forecast(tfp_series, horizon)
                p, d, q = arima_order
                last_fc_year = forecast_df.index.max()
                _arima_forecast_available = True

                # ----- แถบสรุปตัวเลขสำคัญ (KPI) เหนือกราฟ — สรุปให้เห็นภาพรวมได้
                # ในสายตาเดียว ก่อนลงรายละเอียดในกราฟด้านล่าง — รวมเป็นการ์ดเดียว
                # (kpi-strip) แบ่งด้วยเส้นคั่นภายใน แทนกล่องแยก 4 ใบแบบเดิม -----
                # ----- สีไอคอนของ 4 ช่องนี้ -----
                # เดิมใช้สีรุ้ง (ส้ม/ฟ้า/กรมท่า/เขียว) 4 สีต่างกันไปคนละใบ ซึ่งฟ้าสด
                # และเขียวสดไม่ได้อยู่ในโทนสีหลักของแบรนด์ (ส้ม-ขาว-กรมท่า) เลย ทำให้
                # แถวนี้ดูหลุดโทนไปจากส่วนอื่นของแดชบอร์ด — เปลี่ยนมาสลับแค่ 2 สีของ
                # แบรนด์เอง (ไล่เฉดส้มกับไล่เฉดกรมท่า แบบเดียวกับวงกลมไอคอนหัวข้อ
                # section-num ที่ใช้อยู่ทั่วทั้งแอป) ให้เข้าธีมเดียวกันทั้งหมด
                _kpi_orange = "linear-gradient(155deg, var(--brand-orange), var(--brand-orange-dark))"
                _kpi_navy = "linear-gradient(155deg, var(--brand-navy), #0E2436)"
                st.markdown(
                    '<div class="kpi-strip">'
                    + _kpi_strip_item(
                        _kpi_orange, icon("database", 21, 1.8),
                        f"{len(tfp_series)} ปี",
                        # เดิมเขียนว่า "ข้อมูลย้อนหลัง" เฉยๆ ทำให้สับสนกับกราฟด้านล่าง
                        # ที่ตอนนี้ตัดแสดงผลแค่ปี 2000+ (แต่ตัวเลขนี้พูดถึงข้อมูลที่
                        # "ใช้คำนวณ/ฝึกโมเดล" ซึ่งยังเป็นข้อมูลเต็ม 68 ปีเหมือนเดิม
                        # ไม่เกี่ยวกับกราฟแสดงผล) ใช้คำที่ชัดเจนกว่าเดิมแทน
                        f"ข้อมูลที่ใช้คำนวณ<br><span style='white-space:nowrap;'>"
                        f"({tfp_series.index.min()}–{tfp_series.index.max()})</span>",
                    )
                    + _kpi_strip_item(
                        _kpi_navy, icon("trend-up", 21, 1.8),
                        f"{tfp_series.iloc[-1]:.4f}",
                        f"ค่า TFP ล่าสุด (ปี {tfp_series.index.max()})",
                    )
                    + _kpi_strip_item(
                        _kpi_orange, icon("clock", 21, 1.8),
                        f"{horizon} ปี",
                        f"พยากรณ์ล่วงหน้า<br><span style='white-space:nowrap;'>"
                        f"({tfp_series.index.max() + 1}–{last_fc_year})</span>",
                    )
                    + _kpi_strip_item(
                        _kpi_navy, icon("check", 21, 2),
                        f"ARIMA({p},{d},{q})",
                        "เลือกอัตโนมัติ (AIC ต่ำสุด)",
                    )
                    + '</div>',
                    unsafe_allow_html=True,
                )
                st.write("")

                st.markdown(
                    '<p style="font-size:0.76rem;color:var(--brand-navy-soft);margin:0 2px 8px;">'
                    f'{icon("info", 11, 2)} กราฟแสดงข้อมูลตั้งแต่ปี 2000 เป็นต้นไปเพื่อความชัดเจน '
                    f'(โมเดลยังคำนวณจากข้อมูลเต็ม {len(tfp_series)} ปี ตั้งแต่ {tfp_series.index.min()} '
                    f'เหมือนเดิมทุกประการ ไม่กระทบผลพยากรณ์ใดๆ)</p>',
                    unsafe_allow_html=True,
                )
                _nice_line_chart_with_forecast(
                    tfp_series, forecast_df, color="#F97316", forecast_color="#2F6FED", height=340,
                    display_from_year=2000,
                )

                # ----- แถบไฮไลต์ค่าพยากรณ์ปีสุดท้ายของช่วงที่เลือก แทนประโยคยาว
                # เดิมที่อ่านยาก — เน้นตัวเลขสำคัญ 3 ค่า (พยากรณ์ / ขอบล่าง-บน 95%)
                # พร้อมปีที่พยากรณ์ถึงไว้ในแถบเดียวให้เห็นชัดเจน -----
                fc_last = forecast_df.loc[last_fc_year]
                st.markdown(
                    '<div class="fc-highlight-bar">'
                    f'<div class="fc-highlight-item"><div class="fc-highlight-icon">{icon("bars", 17, 1.8)}</div>'
                    f'<div><div class="fc-highlight-value">{fc_last["mean"]:.4f}</div>'
                    f'<div class="fc-highlight-label">ค่าพยากรณ์ปี {last_fc_year}</div></div></div>'
                    f'<div class="fc-highlight-item"><div class="fc-highlight-icon">{icon("trend-down", 17, 1.8)}</div>'
                    f'<div><div class="fc-highlight-value">{fc_last["lower"]:.4f}</div>'
                    f'<div class="fc-highlight-label">ขอบล่าง 95%</div></div></div>'
                    f'<div class="fc-highlight-item"><div class="fc-highlight-icon">{icon("trend-up", 17, 1.8)}</div>'
                    f'<div><div class="fc-highlight-value">{fc_last["upper"]:.4f}</div>'
                    f'<div class="fc-highlight-label">ขอบบน 95%</div></div></div>'
                    f'<div class="fc-highlight-item"><div class="fc-highlight-icon">{icon("sparkle", 17, 1.8)}</div>'
                    f'<div><div class="fc-highlight-value">95%</div>'
                    f'<div class="fc-highlight-label">ความเชื่อมั่นของช่วงพยากรณ์</div></div></div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                # กล่องเดียวรวมทั้งหมายเหตุการเลือก order อัตโนมัติ + expander ตัวเลข
                # พยากรณ์รายปี — เดิมข้อความหมายเหตุลอยเป็นบรรทัดเดี่ยว ๆ แยกจาก
                # expander ที่อยู่ถัดมา ดูไม่เชื่อมกัน จึงรวมไว้ในกรอบเดียวกัน
                with st.container(border=True):
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:7px;font-size:0.78rem;'
                        f'color:var(--brand-navy-soft);line-height:1.5;margin-bottom:6px;">'
                        f'{icon("info", 14, 1.8)}'
                        f'<span>เลือก order ของ ARIMA ด้วยค่า AIC ต่ำสุดจากการลอง grid search อัตโนมัติ</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    with st.expander("📋 ดูตัวเลขพยากรณ์รายปี"):
                        fc_display = forecast_df.rename(
                            columns={"mean": "ค่าพยากรณ์", "lower": "ขอบล่าง 95%", "upper": "ขอบบน 95%"}
                        ).round(4)
                        fc_display.index.name = "ปี"
                        # ตาราง HTML ธีมครีม-ส้ม (คลาส tfp-table-cream) แทน st.dataframe
                        # เดิม เพื่อให้ดีไซน์เข้ากับโทนสีส้ม/ครีมของกราฟพยากรณ์ในส่วนนี้
                        fc_reset = fc_display.reset_index()
                        fc_header_html = "".join(f"<th>{c}</th>" for c in fc_reset.columns)
                        fc_rows_html = "".join(
                            "<tr>" + "".join(
                                f"<td>{int(v) if col == 'ปี' else f'{v:,.4f}'}</td>"
                                for col, v in zip(fc_reset.columns, row)
                            ) + "</tr>"
                            for row in fc_reset.values.tolist()
                        )
                        st.markdown(
                            f'<div style="overflow-x:auto;"><table class="tfp-table-cream"><thead><tr>'
                            f'{fc_header_html}</tr></thead><tbody>{fc_rows_html}</tbody></table></div>',
                            unsafe_allow_html=True,
                        )
                        fc_csv = fc_display.to_csv().encode("utf-8-sig")
                        st.download_button(
                            "ดาวน์โหลดตัวเลขพยากรณ์เป็น CSV",
                            data=fc_csv,
                            file_name="TFP_forecast_ARIMA.csv",
                            mime="text/csv",
                        )

                # ================= ทดสอบความแม่นยำของโมเดลย้อนหลัง (Backtesting) =================
                # ไม่ใช้ทฤษฎีใหม่เพิ่มเติมจากที่มีอยู่แล้ว — เรียก _auto_arima_forecast
                # ตัวเดิมซ้ำ โดยซ่อนข้อมูลปีล่าสุดไว้ชั่วคราวแล้วให้โมเดลทายปีที่ซ่อนไว้
                # จากนั้นเทียบกับค่าจริงที่รู้อยู่แล้ว พร้อม Naive forecast เป็นเส้นฐาน
                with st.expander("🎯 ทดสอบความแม่นยำของโมเดลย้อนหลัง (Backtesting)"):
                    st.markdown(
                        '<p style="font-size:0.85rem;color:var(--brand-navy-soft);line-height:1.65;'
                        'margin-top:0;">ทดสอบว่า ถ้าเราไม่รู้ผลจริงของปีล่าสุด ๆ แล้วให้แบบจำลอง ARIMA '
                        'ทายปีเหล่านั้นจากข้อมูลก่อนหน้า จะทายได้ใกล้เคียงค่าจริงแค่ไหน — '
                        'เทียบกับ "Naive forecast" <span style="white-space:nowrap;">(สมมติค่าปีสุดท้ายคงที่ไปเรื่อย ๆ '
                        'โดยไม่ใช้แบบจำลองใดเลย) เป็นเส้นฐานว่า ARIMA ทายแม่นกว่าการเดาเปล่า ๆ แค่ไหน</span></p>',
                        unsafe_allow_html=True,
                    )
                    bt_df, bt_metrics, bt_err = _run_backtest(tfp_series, min_train=MIN_POINTS_FOR_ARIMA)
                    if bt_err:
                        st.info(bt_err)
                    else:
                        _bt_better = bt_metrics["arima_mape"] < bt_metrics["naive_mape"]
                        _bt_cols = st.columns(2)
                        with _bt_cols[0]:
                            st.markdown(
                                f'<div style="position:relative;">'
                                + (f'<div style="position:absolute;top:-9px;right:14px;z-index:2;'
                                   f'background:linear-gradient(135deg,var(--green),#0F7A38);color:#fff;'
                                   f'font-size:0.66rem;font-weight:700;padding:3px 10px;border-radius:999px;'
                                   f'box-shadow:0 4px 10px rgba(22,163,74,0.35);">{icon("check", 10, 2.5)} แม่นกว่า</div>'
                                   if _bt_better else '')
                                + _dash_kpi_card(
                                    "#16324A", icon("check" if _bt_better else "alert", 18, 1.8),
                                    f'{bt_metrics["arima_mape"]:.2f}%',
                                    f'ค่าเฉลี่ยความคลาดเคลื่อน ARIMA (MAPE, ทดสอบ {bt_metrics["test_years"]} ปีล่าสุด)',
                                )
                                + '</div>',
                                unsafe_allow_html=True,
                            )
                        with _bt_cols[1]:
                            st.markdown(
                                f'<div style="position:relative;">'
                                + (f'<div style="position:absolute;top:-9px;right:14px;z-index:2;'
                                   f'background:linear-gradient(135deg,var(--green),#0F7A38);color:#fff;'
                                   f'font-size:0.66rem;font-weight:700;padding:3px 10px;border-radius:999px;'
                                   f'box-shadow:0 4px 10px rgba(22,163,74,0.35);">{icon("check", 10, 2.5)} แม่นกว่า</div>'
                                   if not _bt_better else '')
                                + _dash_kpi_card(
                                    "#F97316", icon("bars", 18, 1.8),
                                    f'{bt_metrics["naive_mape"]:.2f}%',
                                    "ค่าเฉลี่ยความคลาดเคลื่อน Naive (เส้นฐานเทียบ)",
                                )
                                + '</div>',
                                unsafe_allow_html=True,
                            )
                        # แถบเทียบขนาดความคลาดเคลื่อนแบบภาพ (เห็นสัดส่วนได้ไวกว่าตัวเลขล้วน)
                        _mape_max = max(bt_metrics["arima_mape"], bt_metrics["naive_mape"], 0.01)
                        st.markdown(
                            '<div style="margin:14px 2px 4px;">'
                            + f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
                              f'<span style="width:52px;font-size:0.76rem;color:var(--brand-navy-soft);flex-shrink:0;">ARIMA</span>'
                              f'<div style="flex:1;background:#EDE7DA;border-radius:999px;height:8px;overflow:hidden;">'
                              f'<div style="width:{bt_metrics["arima_mape"] / _mape_max * 100:.0f}%;height:100%;'
                              f'background:linear-gradient(90deg,#16324A,#0E2436);border-radius:999px;"></div></div>'
                              f'<span style="width:52px;font-size:0.76rem;color:var(--brand-navy);font-weight:700;text-align:right;">'
                              f'{bt_metrics["arima_mape"]:.2f}%</span></div>'
                            + f'<div style="display:flex;align-items:center;gap:10px;">'
                              f'<span style="width:52px;font-size:0.76rem;color:var(--brand-navy-soft);flex-shrink:0;">Naive</span>'
                              f'<div style="flex:1;background:#EDE7DA;border-radius:999px;height:8px;overflow:hidden;">'
                              f'<div style="width:{bt_metrics["naive_mape"] / _mape_max * 100:.0f}%;height:100%;'
                              f'background:linear-gradient(90deg,var(--brand-orange),var(--brand-orange-dark));border-radius:999px;"></div></div>'
                              f'<span style="width:52px;font-size:0.76rem;color:var(--brand-navy);font-weight:700;text-align:right;">'
                              f'{bt_metrics["naive_mape"]:.2f}%</span></div>'
                            + '</div>',
                            unsafe_allow_html=True,
                        )
                        st.write("")
                        _bt_reset = bt_df.reset_index()
                        _bt_rows_html = ""
                        for _, r in _bt_reset.iterrows():
                            # ไฮไลต์ค่าที่ทายใกล้เคียงค่าจริงกว่าในแต่ละปีด้วยสีเขียว+ตัวหนา
                            # ให้เห็นเป็นภาพว่าปีไหน ARIMA ชนะ ปีไหน Naive ชนะ ไม่ต้องนั่งลบเลขเอง
                            _arima_diff = abs(r["ARIMA"] - r["ค่าจริง"])
                            _naive_diff = abs(r["Naive"] - r["ค่าจริง"])
                            _arima_style = "color:var(--green);font-weight:700;" if _arima_diff <= _naive_diff else ""
                            _naive_style = "color:var(--green);font-weight:700;" if _naive_diff < _arima_diff else ""
                            _bt_rows_html += (
                                f'<tr><td>{int(r["ปี"])}</td><td>{r["ค่าจริง"]:,.2f}</td>'
                                f'<td style="{_arima_style}">{r["ARIMA"]:,.2f}</td>'
                                f'<td style="{_naive_style}">{r["Naive"]:,.2f}</td></tr>'
                            )
                        st.markdown(
                            f'<div class="backtest-table" style="overflow-x:auto;"><table class="tfp-table-cream">'
                            f'<thead><tr><th>ปี</th><th>ค่าจริง</th><th>ARIMA ทาย</th><th>Naive ทาย</th></tr></thead>'
                            f'<tbody>{_bt_rows_html}</tbody></table></div>'
                            f'<p style="font-size:0.72rem;color:var(--brand-navy-soft);margin:6px 2px 0;">'
                            f'{icon("check", 10, 2.5)} <span style="color:var(--green);font-weight:600;">ตัวเลขสีเขียว</span> '
                            f'= ค่าทายที่ใกล้เคียงค่าจริงกว่าในปีนั้น</p>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f'<p style="font-size:0.82rem;color:var(--brand-navy-soft);margin-top:10px;">'
                            f'ฝึกโมเดลด้วยข้อมูล {bt_metrics["train_years"]} ปีแรก แล้วทดสอบทาย '
                            f'{bt_metrics["test_years"]} ปีสุดท้าย (เลือก ARIMA{bt_metrics["order"]} ด้วย AIC) — '
                            f'<span style="white-space:nowrap;">'
                            + ('ARIMA ทายแม่นกว่า Naive ในช่วงทดสอบนี้'
                               if _bt_better else
                               'ในช่วงทดสอบนี้ Naive ทายใกล้เคียงหรือแม่นกว่า ARIMA เล็กน้อย '
                               'ซึ่งเกิดขึ้นได้กับอนุกรมเวลาสั้น ๆ ควรตีความผลด้วยความระมัดระวัง')
                            + '</span></p>',
                            unsafe_allow_html=True,
                        )
            else:
                _nice_line_chart(tfp_series, color="#F97316", height=340)
                st.caption(
                    f"ข้อมูล {len(tfp_series)} ปี (ปี {tfp_series.index.min()}–{tfp_series.index.max()}) "
                    f"| ค่าล่าสุด = {tfp_series.iloc[-1]:.4f}"
                )
                st.info(
                    f"ข้อมูลมีเพียง {len(tfp_series)} ปี ยังไม่พอสำหรับพยากรณ์ด้วย ARIMA "
                    f"อย่างน่าเชื่อถือ (ต้องการอย่างน้อย {MIN_POINTS_FOR_ARIMA} ปี)"
                )
        st.markdown('</div>', unsafe_allow_html=True)

        # ================= การ์ดสรุปภาพรวมผลการพยากรณ์ (พื้นกรมท่าเข้ม) =================
        if _arima_forecast_available:
            fc_final = float(forecast_df.loc[last_fc_year, "mean"])
            base_val = float(tfp_series.iloc[-1])
            base_year = int(tfp_series.index.max())
            n_years_fc = int(last_fc_year) - base_year
            growth_total = ((fc_final / base_val) - 1) * 100 if base_val else 0.0
            cagr = (((fc_final / base_val) ** (1 / n_years_fc)) - 1) * 100 if base_val and n_years_fc > 0 else 0.0
            _trend_icon = "trend-up" if growth_total >= 0 else "trend-down"
            _trend_word = "เพิ่มขึ้น" if growth_total >= 0 else "ลดลง"
            st.markdown(
                f'<div class="nxpo-summary-card">'
                f'<div class="label">{icon("sparkle", 14, 2)} ภาพรวมผลการพยากรณ์</div>'
                f'<div class="value-sub">TFP ปี {last_fc_year} (พยากรณ์)</div>'
                f'<div class="value">{fc_final:,.2f}'
                f'<span class="growth-badge">{icon(_trend_icon, 13, 2)} {growth_total:+.1f}%</span></div>'
                f'<div class="from-label">จากปี {base_year} ({base_val:,.2f})</div>'
                f'<div class="divider"></div>'
                f'<div class="trend-title">แนวโน้มในช่วง {n_years_fc} ปีข้างหน้า</div>'
                f'<ul class="nxpo-summary-list">'
                f'<li><span class="tick">{icon("check", 11, 2.4)}</span>TFP มีแนวโน้ม{_trend_word}อย่างต่อเนื่อง</li>'
                f'<li><span class="tick">{icon("check", 11, 2.4)}</span>อัตราการเติบโตเฉลี่ย (CAGR) {cagr:+.1f}% ต่อปี</li>'
                f'<li><span class="tick">{icon("check", 11, 2.4)}</span>ส่งผลต่อผลิตภาพการผลิตและเศรษฐกิจไทยโดยรวม</li>'
                f'</ul></div>',
                unsafe_allow_html=True,
            )
            st.write("")

        # ================= กราฟรายตัวแปร: แยกกล่องระยะยาว / ระยะสั้น =================
        # แยกรายชื่อตัวแปรอิสระเป็น 2 ชุดตามสมการที่ตัวแปรนั้นอยู่ แทนที่จะรวมเป็น
        # dropdown เดียว — ตัวแปรที่อยู่ในทั้งสองสมการจะไปโผล่ทั้งสองกล่อง (ถูกต้อง
        # เพราะมันมีทั้งผลระยะยาวและระยะสั้นจริง ๆ)
        available_vars_lr = [v for v in active_lr_vars if v != "const" and v in model_df.columns]
        available_vars_sr = [v for v in active_sr_bases if v in model_df.columns]

        def _var_trend_box(title_th: str, options: list, widget_key: str,
                            icon_name: str = "trend-up", accent: str = "#D8A867"):
            """วาดกล่อง selectbox + กราฟเส้นแนวโน้มของตัวแปร 1 ชุด (ยาว หรือ สั้น)
            คืนค่าตัวแปรที่ผู้ใช้เลือกอยู่ในกล่องนี้ (หรือ None ถ้าไม่มีตัวแปรให้เลือก)"""
            # หัวข้อ: แถบหัวเรียบ ๆ (ไอคอนสี่เหลี่ยมมุมมน + ข้อความ) แบบเดียวกับหัวข้อ
            # ส่วนอื่น ๆ ในแอป — เดิมเป็นแคปซูลลอยกลางจอพร้อมแถบสีทึบโผล่ใต้แคปซูล
            # ซึ่งดูแปลกและหลุดโทนจากดีไซน์ส่วนอื่นของหน้า จึงตัดออกให้เรียบขึ้น
            st.markdown(
                f"""
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
                    <div style="width:34px;height:34px;border-radius:10px;flex-shrink:0;
                                background:{accent};color:#FFFFFF;display:flex;
                                align-items:center;justify-content:center;
                                box-shadow:0 4px 10px {accent}4D;">
                        {icon(icon_name, 16, 2)}
                    </div>
                    <span style="font-family:var(--font-elegant);font-weight:600;font-size:1rem;
                                 color:var(--brand-navy);letter-spacing:-0.01em;">{title_th}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not options:
                st.info("ไม่พบข้อมูลตัวแปรอิสระในชุดนี้")
                return None
            # กรอบพื้นหลังสีขาวครอบกล่องทั้งก้อน + ช่อง selectbox ตรงกลางสีครีม
            # (สไตล์เดียวกับกล่อง "สมมติตัวแปรเปลี่ยนแปลง" ด้านล่างของหน้านี้)
            st.markdown(
                f"""
                <style>
                .st-key-vartrend_box_{widget_key} {{
                    background: #FFFFFF !important;
                    padding: 22px 22px !important;
                    margin-top: -14px !important;
                }}
                .st-key-vartrend_box_{widget_key} div[data-baseweb="select"] > div {{
                    background: var(--bg-page) !important;
                    border-color: #E7DFCF !important;
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
            with st.container(border=True, key=f"vartrend_box_{widget_key}"):
                picked = st.selectbox(
                    "เลือกตัวแปรอิสระที่ต้องการดูกราฟ",
                    options=options,
                    format_func=var_label_with_abbr,
                    key=widget_key,
                )
            series = model_df[picked].dropna().sort_index()
            if series.empty:
                st.info("ไม่พบข้อมูลของตัวแปรนี้")
            else:
                _nice_line_chart(series, color="#2F6FED", height=280)
                st.markdown(
                    f'<div style="text-align:center;color:var(--brand-navy-soft);'
                    f'font-size:0.85rem;margin-top:2px;">'
                    f'{var_label_with_abbr(picked)} — ข้อมูล {len(series)} ปี</div>',
                    unsafe_allow_html=True,
                )
            return picked

        st.markdown(
            f'<div class="section-card"><div class="section-title">'
            f'<div class="section-num">{icon("search", 19, 1.8)}</div>'
            f'<div class="section-title-text"><h3>กราฟแนวโน้มตัวแปรอิสระรายตัว</h3>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        col_lr, col_sr = st.columns(2, gap="large")
        with col_lr:
            chosen_var_lr = _var_trend_box(
                "ตัวแปรอิสระที่ส่งผลระยะยาว", available_vars_lr, "dashboard_var_select_lr",
                icon_name="trend-up", accent="#D8A867",
            )
        with col_sr:
            chosen_var_sr = _var_trend_box(
                "ตัวแปรอิสระที่ส่งผลระยะสั้น", available_vars_sr, "dashboard_var_select_sr",
                icon_name="trend-down", accent="#D8A867",
            )
        st.markdown('</div>', unsafe_allow_html=True)

        # การ์ดผลกระทบด้านล่าง (คำนวณจากค่าความยืดหยุ่น/สัมประสิทธิ์ระยะยาว) ยังคง
        # อ้างอิงตัวแปรที่เลือกในกล่อง "ระยะยาว" เป็นหลัก เพราะสูตร % ผลกระทบสร้างจาก
        # สัมประสิทธิ์ log-log ของสมการระยะยาว (ตัวแปรระยะสั้นจะโชว์เป็นข้อมูลเสริม
        # ในหมายเหตุท้ายการ์ดอยู่แล้วถ้ามีค่าสัมประสิทธิ์ระยะสั้นของตัวแปรเดียวกัน)
        chosen_var = chosen_var_lr
        available_vars = available_vars_lr

        # ================= การ์ดผลกระทบของตัวแปรที่เลือกต่อ TFP (% จากค่าความยืดหยุ่น) =================
        if available_vars:
            st.markdown(
                f'<div class="section-card"><div class="section-title">'
                f'<div class="section-num">{icon("bulb", 20, 1.6)}</div>'
                f'<div class="section-title-text"><h3>ตัวแปรนี้ส่งผลต่อ TFP มากน้อยแค่ไหน</h3>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            lr_info = lr_raw_map.get(chosen_var)
            sr_info = sr_raw_map.get(chosen_var)
            full_name = _var_full_name(chosen_var)
            is_log = chosen_var.startswith("ln_")

            if lr_info is None:
                st.info(
                    f"'{var_label_with_abbr(chosen_var)}' ไม่ได้อยู่ในสมการระยะยาวชุดปัจจุบัน "
                    f"จึงยังไม่มีค่าสัมประสิทธิ์ให้คำนวณผลกระทบ"
                )
            else:
                coef = lr_info["coef"]
                p_val = lr_info["p"]
                star = _significance_stars(p_val)
                sig_text = {
                    "***": "มีนัยสำคัญทางสถิติสูงมาก (ความเชื่อมั่น 99%)",
                    "**": "มีนัยสำคัญทางสถิติ (ความเชื่อมั่น 95%)",
                    "*": "มีนัยสำคัญทางสถิติเล็กน้อย (ความเชื่อมั่น 90%)",
                    "": "ยังไม่มีนัยสำคัญทางสถิติในระดับที่ยอมรับได้ทั่วไป — ควรตีความตัวเลขด้วยความระมัดระวัง",
                }[star]

                # กรอบพื้นหลังสีขาวครอบกล่อง input ทั้งก้อน + ช่องตัวเลขตรงกลางสีครีม
                # ให้ตัดกับกรอบขาวรอบนอก + ปุ่ม +/- เป็นสีเขียว/แดงค้างไว้ตลอด (ไม่ใช่แค่
                # ตอน hover) ให้ผู้ใช้เห็นชัดว่าปุ่มไหนเพิ่ม/ปุ่มไหนลดค่าโดยไม่ต้องอ่านสัญลักษณ์
                st.markdown(
                    """
                    <style>
                    .st-key-shock_input_box {
                        background: #FFFFFF !important;
                        padding: 22px 22px !important;
                    }
                    div[data-testid="stNumberInput"] div[data-baseweb="input"] {
                        background: var(--bg-page) !important;
                        border: 1.5px solid #E7DFCF !important;
                        border-radius: 8px !important;
                        box-shadow: none !important;
                    }
                    div[data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within {
                        border: 1.5px solid var(--brand-orange) !important;
                        box-shadow: none !important;
                    }
                    div[data-testid="stNumberInput"] input {
                        background: transparent !important;
                        color: var(--brand-navy) !important;
                        font-weight: 700 !important;
                    }
                    /* ปุ่ม + สีเขียว / ปุ่ม − สีแดง ค้างไว้ตลอดเวลา (ไม่ใช่แค่ตอน hover) */
                    button[data-testid="stNumberInputStepUp"],
                    button[aria-label="Increment"] {
                        background: #16A34A !important; border-color: #16A34A !important;
                    }
                    button[data-testid="stNumberInputStepUp"]:hover,
                    button[aria-label="Increment"]:hover {
                        background: #128A3B !important; border-color: #128A3B !important;
                    }
                    button[data-testid="stNumberInputStepUp"] svg,
                    button[aria-label="Increment"] svg { color: #FFFFFF !important; fill: #FFFFFF !important; }
                    button[data-testid="stNumberInputStepDown"],
                    button[aria-label="Decrement"] {
                        background: #EF4444 !important; border-color: #EF4444 !important;
                    }
                    button[data-testid="stNumberInputStepDown"]:hover,
                    button[aria-label="Decrement"]:hover {
                        background: #D63A3A !important; border-color: #D63A3A !important;
                    }
                    button[data-testid="stNumberInputStepDown"] svg,
                    button[aria-label="Decrement"] svg { color: #FFFFFF !important; fill: #FFFFFF !important; }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )

                shock_col, result_col = st.columns([1, 1.3])
                with shock_col:
                    with st.container(border=True, key="shock_input_box"):
                        if is_log:
                            shock = st.number_input(
                                f"สมมติ {full_name} เปลี่ยนแปลง (%)",
                                min_value=-50.0, max_value=50.0, value=1.0, step=0.5,
                                key=f"impact_shock_{chosen_var}",
                            )
                            pct_effect = coef * shock
                            formula_text = (
                                f'<div>ค่าความยืดหยุ่น (elasticity) จากสมการระยะยาว = {coef:.4f}</div>'
                                f'<div style="margin-top:6px;">→ TFP เปลี่ยนแปลง ≈ {coef:.4f} × {shock:g}%</div>'
                            )
                        else:
                            shock = st.number_input(
                                f"สมมติ {full_name} เปลี่ยนแปลง",
                                value=1.0, step=0.5,
                                key=f"impact_shock_{chosen_var}",
                            )
                            pct_effect = (math.exp(coef * shock) - 1) * 100
                            formula_text = (
                                f'<div>สัมประสิทธิ์จากสมการระยะยาว = {coef:.4f} '
                                f'(ตัวแปรนี้ไม่ได้อยู่ในรูป log จึงตีความเป็น semi-elasticity)</div>'
                                f'<div style="margin-top:6px;">→ TFP เปลี่ยนแปลง ≈ '
                                f'(e^({coef:.4f}×{shock:g}) − 1) × 100%</div>'
                            )
                        st.markdown(
                            '<div style="font-size:0.82rem;color:var(--brand-navy-soft);'
                            'line-height:1.5;margin-top:-4px;">'
                            'ปรับตัวเลขด้านบนเพื่อดูว่าถ้าตัวแปรนี้เปลี่ยนแปลงมากน้อยต่างกัน<br>'
                            'TFP จะเปลี่ยนไปกี่ % (คำนวณจากค่าสัมประสิทธิ์ในสมการระยะยาวปัจจุบัน)'
                            '</div>',
                            unsafe_allow_html=True,
                        )

                with result_col:
                    arrow = "↑" if pct_effect >= 0 else "↓"
                    color = "var(--green)" if pct_effect >= 0 else "var(--red)"

                    # ป้ายนัยสำคัญ: สี/ข้อความ ตามระดับดาว (***/**/*/ไม่มี) ให้ดูเป็น badge
                    # เดียวกันแทนที่จะเป็นประโยคลอย ๆ แยกก้อนเหมือนก่อนหน้านี้
                    badge_map = {
                        "***": ("var(--green)", "#E9F9EE", "นัยสำคัญสูงมาก (ความเชื่อมั่น 99%)"),
                        "**": ("var(--green)", "#E9F9EE", "มีนัยสำคัญ (ความเชื่อมั่น 95%)"),
                        "*": ("#B45309", "#FEF3E2", "นัยสำคัญเล็กน้อย (ความเชื่อมั่น 90%)"),
                        "": ("var(--red)", "#FDEDED", "ยังไม่มีนัยสำคัญทางสถิติในระดับที่ยอมรับได้ทั่วไป"),
                    }
                    badge_color, badge_bg, badge_text = badge_map[star]
                    p_text = f"p-value = {p_val:.4f}" if p_val is not None else "ไม่พบค่า p-value"

                    # กรอบขาวเข้ม (border ชัดขึ้น + เงาบาง ๆ) แยกกล่องผลลัพธ์ให้เด่นออกจาก
                    # พื้นหลังหน้าเว็บ แทนกล่องเทาอ่อนแบบเดิมที่กลืนไปกับพื้น
                    st.markdown(
                        f'<div style="background:#FFFFFF;border:1.5px solid #D6DCE5;'
                        f'border-radius:12px;padding:18px 20px;'
                        f'box-shadow:0 1px 4px rgba(15,23,42,0.06);">'
                        f'<div style="font-size:0.78rem;font-weight:600;color:var(--brand-navy-soft);'
                        f'text-transform:uppercase;letter-spacing:.02em;">'
                        f'ผลกระทบต่อดัชนี TFP (สมการระยะยาว)</div>'
                        f'<div style="display:flex;align-items:baseline;gap:8px;margin-top:6px;">'
                        f'<span style="font-size:1.1rem;color:{color};">{arrow}</span>'
                        f'<span style="font-size:1.65rem;font-weight:800;color:{color};line-height:1;">'
                        f'{pct_effect:+.2f}%</span>'
                        f'</div>'
                        f'<div style="font-size:0.78rem;color:var(--brand-navy-soft);margin-top:10px;'
                        f'line-height:1.6;">{formula_text}</div>'
                        f'<div style="height:1px;background:var(--card-border);margin:14px 0 12px;"></div>'
                        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
                        f'row-gap:8px;">'
                        f'<span style="background:{badge_bg};color:{badge_color};font-size:0.74rem;'
                        f'font-weight:700;padding:5px 12px;border-radius:999px;line-height:1.4;'
                        f'display:inline-block;">'
                        f'{badge_text}</span>'
                        f'<span style="font-size:0.74rem;color:var(--brand-navy-soft);white-space:nowrap;">'
                        f'{p_text}</span>'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                # แถวหมายเหตุด้านล่าง (short-run + ceteris paribus) รวมเป็นกล่องเดียว
                # กั้นด้วยเส้นประบาง ๆ จากส่วนบน แทนที่จะเป็น caption ลอย ๆ หลายบรรทัด
                footer_rows = []
                if sr_info is not None:
                    footer_rows.append(
                        '<div style="display:flex;gap:10px;">'
                        f'<span style="flex:none;color:var(--brand-orange-dark);">{icon("clock", 14, 1.6)}</span>'
                        '<span><b style="color:var(--brand-navy);">ผลกระทบระยะสั้น (short-run):</b> '
                        f'สัมประสิทธิ์ = {sr_info["coef"]:.4f} — สะท้อนผลของการเปลี่ยนแปลงตัวแปรนี้ในปีนั้น ๆ '
                        'ต่อการเปลี่ยนแปลง TFP ในปีเดียวกัน (คนละความหมายกับผลระยะยาวด้านบน)</span>'
                        '</div>'
                    )
                footer_rows.append(
                    '<div style="display:flex;gap:10px;">'
                    f'<span style="flex:none;color:var(--brand-orange-dark);">{icon("info", 14, 1.6)}</span>'
                    '<span><b style="color:var(--brand-navy);">หมายเหตุ:</b> ตัวเลข % นี้เป็นผลกระทบจากตัวแปรนี้ '
                    '“ตัวเดียว” โดยสมมติให้ตัวแปรอื่นคงที่ (ceteris paribus) ไม่ใช่การพยากรณ์ TFP จริง '
                    'ที่มีหลายปัจจัยเปลี่ยนแปลงพร้อมกัน</span>'
                    '</div>'
                )
                st.markdown(
                    '<div style="margin-top:16px;padding-top:14px;border-top:1px dashed var(--card-border);'
                    'display:flex;flex-direction:column;gap:10px;font-size:0.8rem;'
                    'color:var(--brand-navy-soft);line-height:1.55;">'
                    + "".join(footer_rows) +
                    '</div>',
                    unsafe_allow_html=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)

        # ================= กราฟสัดส่วนอิทธิพลเทียบกันทุกตัวแปร (Standardized Coefficient) =================
        st.markdown(
            f'<div class="section-card"><div class="section-title">'
            f'<div class="section-num">{icon("bars", 19, 1.8)}</div>'
            f'<div class="section-title-text"><h3>สัดส่วนอิทธิพลเทียบกันทุกตัวแปร (%)</h3>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        influence_vars = [
            v for v in active_lr_vars
            if v != "const" and v in lr_raw_map and v in model_df.columns
        ]
        if len(influence_vars) < 2:
            st.info("ต้องมีตัวแปรอิสระอย่างน้อย 2 ตัวในสมการระยะยาว จึงจะเทียบสัดส่วนอิทธิพลกันได้")
        else:
            sample_df = model_df[[dep_ln] + influence_vars].dropna()
            y_std = sample_df[dep_ln].std() if not sample_df.empty else None
            if sample_df.empty or len(sample_df) < 3 or not y_std or pd.isna(y_std):
                st.info("ข้อมูลไม่พอสำหรับคำนวณสัดส่วนอิทธิพล (ต้องการอย่างน้อย 3 ปีที่มีข้อมูลครบทุกตัวแปร)")
            else:
                rows = []
                for v in influence_vars:
                    x_std = sample_df[v].std()
                    if not x_std or pd.isna(x_std) or x_std == 0:
                        continue
                    std_beta = lr_raw_map[v]["coef"] * (x_std / y_std)
                    rows.append({"code": v, "label": _var_full_name(v), "std_beta": std_beta})

                if not rows:
                    st.info("ไม่สามารถคำนวณสัดส่วนอิทธิพลได้ (ส่วนเบี่ยงเบนมาตรฐานของตัวแปรบางตัวเป็น 0)")
                else:
                    infl_df = pd.DataFrame(rows)
                    infl_df["abs_beta"] = infl_df["std_beta"].abs()
                    total_abs = infl_df["abs_beta"].sum()
                    infl_df["สัดส่วน (%)"] = infl_df["abs_beta"] / total_abs * 100
                    infl_df["ทิศทาง"] = infl_df["std_beta"].apply(
                        lambda x: "หนุนเสริม TFP (+)" if x >= 0 else "ฉุดรั้ง TFP (−)"
                    )
                    infl_df = infl_df.sort_values("สัดส่วน (%)", ascending=False).reset_index(drop=True)

                    dir_scale = alt.Scale(
                        domain=["หนุนเสริม TFP (+)", "ฉุดรั้ง TFP (−)"], range=["#16A34A", "#EF4444"],
                    )
                    y_axis_labels = alt.Axis(domain=False, tickColor="#E9ECF1",
                                              labelColor="#16324A", labelFontSize=12, labelLimit=340)
                    x_axis = alt.Axis(grid=True, gridColor="#EEF1F5", gridDash=[3, 3],
                                       domain=False, tickColor="#E9ECF1",
                                       labelColor="#5B6B7C", labelFontSize=11, tickCount=6)

                    # ขยาย domain ของแกน x ให้กว้างกว่าค่ามากที่สุดเล็กน้อย (~18%) กันตัวเลข
                    # ท้ายแท่ง (เช่น 42.0) ที่วางต่อจากแท่งยาวสุดโดนตัดขอบขวาของกราฟ
                    max_pct = float(infl_df["สัดส่วน (%)"].max())
                    pct_scale = alt.Scale(domain=[0, max_pct * 1.18], nice=False)

                    bars = alt.Chart(infl_df).mark_bar(
                        cornerRadiusTopRight=6, cornerRadiusBottomRight=6, height=18,
                    ).encode(
                        x=alt.X("สัดส่วน (%):Q", title=None, axis=x_axis, scale=pct_scale),
                        y=alt.Y("label:N", sort="-x", title=None, axis=y_axis_labels),
                        color=alt.Color("ทิศทาง:N", scale=dir_scale,
                                         legend=alt.Legend(title=None, orient="bottom")),
                        tooltip=[
                            alt.Tooltip("label:N", title="ตัวแปร"),
                            alt.Tooltip("สัดส่วน (%):Q", title="สัดส่วนอิทธิพล", format=".1f"),
                            alt.Tooltip("std_beta:Q", title="Standardized coefficient", format=".4f"),
                            alt.Tooltip("ทิศทาง:N", title="ทิศทาง"),
                        ],
                    )
                    text = alt.Chart(infl_df).mark_text(align="left", dx=5, color="#5B6B7C", fontSize=11).encode(
                        x=alt.X("สัดส่วน (%):Q", scale=pct_scale),
                        y=alt.Y("label:N", sort="-x"),
                        text=alt.Text("สัดส่วน (%):Q", format=".1f"),
                    )
                    chart = (
                        (bars + text)
                        .properties(
                            height=max(220, 42 * len(infl_df)),
                            padding={"left": 15, "right": 15, "top": 5, "bottom": 5},
                            autosize=alt.AutoSizeParams(type="fit", contains="padding"),
                        )
                        .configure_view(strokeWidth=0)
                        .configure_axis(labelFont=FONT_FAMILY, titleFont=FONT_FAMILY)
                        .configure_legend(labelFont=FONT_FAMILY, labelFontSize=12, symbolType="circle")
                    )
                    st.altair_chart(chart, use_container_width=True)
                    st.caption(
                        "คำนวณจาก standardized coefficient (สัมประสิทธิ์ × ส่วนเบี่ยงเบนมาตรฐานของตัวแปรนั้น "
                        "÷ ส่วนเบี่ยงเบนมาตรฐานของ TFP) แล้วนำค่าสัมบูรณ์มาคิดเป็นสัดส่วน % เทียบกันทุกตัวแปร "
                        "ในสมการระยะยาวชุดปัจจุบัน (รวมกันได้ 100%) — เป็นการเทียบ 'น้ำหนักอิทธิพล' ไม่ใช่ "
                        "หน่วยดิบของตัวแปร จึงเทียบข้ามตัวแปรที่มีหน่วยต่างกันได้"
                    )

                    with st.expander("📋 ดูตารางตัวเลข"):
                        table_display = infl_df[["label", "std_beta", "สัดส่วน (%)", "ทิศทาง"]].rename(
                            columns={"label": "ตัวแปร", "std_beta": "Standardized coefficient"}
                        ).round({"Standardized coefficient": 4, "สัดส่วน (%)": 2})
                        # ใช้ตาราง HTML แบบเดียวกับตาราง Diagnostics (คลาส tfp-table)
                        # แทน st.dataframe เพราะ st.dataframe จัดตำแหน่งตัวอักษรราย
                        # คอลัมน์เองไม่ได้ ส่วน tfp-table กำหนด text-align: center
                        # ให้ทุกคอลัมน์ไว้แล้วในสไตล์ชีตด้านบน (ดูตรงคอมเมนต์
                        # "ตาราง HTML สำหรับ Diagnostics")
                        infl_header_html = "".join(f"<th>{c}</th>" for c in table_display.columns)
                        infl_rows_html = "".join(
                            "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"
                            for row in table_display.values.tolist()
                        )
                        st.markdown(
                            f'<div style="overflow-x:auto;"><table class="tfp-table"><thead><tr>'
                            f'{infl_header_html}</tr></thead><tbody>{infl_rows_html}</tbody></table></div>',
                            unsafe_allow_html=True,
                        )
                        st.download_button(
                            "ดาวน์โหลดตาราง (.csv)",
                            data=table_display.to_csv(index=False).encode("utf-8-sig"),
                            file_name="TFP_influence_share.csv",
                            mime="text/csv",
                            key="dl_influence_share",
                        )
        st.markdown('</div>', unsafe_allow_html=True)

        # ================= ปุ่มไปหน้า "แดชบอร์ดสำหรับนำเสนอ (สรุปหน้าเดียว)" =================
        # เก็บช่วงปีพยากรณ์ + สมมติฐานตัวแปรที่ตั้งไว้ในหน้านี้ (horizon, ตัวแปรที่
        # เลือกในกล่อง "ผลกระทบของตัวแปร", ค่าที่สมมติเปลี่ยนแปลง) ไว้ใน session_state
        # ก่อนพาไปหน้าแดชบอร์ดสรุป เพื่อให้หน้านั้นแสดงผลตรงกับที่ตั้งค่าไว้ที่นี่ทันที
        # โดยไม่ต้องมาตั้งซ้ำ — เหมาะสำหรับเปิดฉายนำเสนอแบบไม่ต้องเลื่อนจอ
        if _arima_forecast_available:
            st.write("")
            with st.container(key="exec_cta_card"):
                st.markdown(
                    '<div class="exec-cta-eyebrow">' + icon("sparkle", 13, 1.8) +
                    'PRESENTATION DASHBOARD</div>'
                    '<div class="exec-cta-inner">'
                    '<p>ตั้งค่าช่วงปีพยากรณ์และสมมติฐานตัวแปรด้านบนตามต้องการแล้ว กดปุ่มด้านล่างเพื่อสรุปทุกอย่างไว้ในหน้าเดียวสำหรับนำเสนอ</p></div>',
                    unsafe_allow_html=True,
                )
                _go_exec_clicked = st.button(
                    "สร้างแดชบอร์ดสำหรับนำเสนอ (สรุปหน้าเดียว)  →",
                    key="forecast_goto_exec_dash", type="primary",
                )
            if _go_exec_clicked:
                st.session_state.exec_dash_horizon = horizon
                st.session_state.exec_dash_chosen_var = chosen_var
                st.session_state.page = "exec_dashboard"
                st.rerun()

# ------------------------------------------------------------------------------
# หน้า "แดชบอร์ดสำหรับนำเสนอ (สรุปหน้าเดียว)" — สรุปผลพยากรณ์ + สมมติฐานที่ตั้งไว้จาก
# หน้า "พยากรณ์ TFP" มาแสดงในมุมมองเดียวแบบกระชับที่สุด (การ์ด KPI + กราฟหลัก +
# ตารางพยากรณ์ย่อ + สัดส่วนอิทธิพลตัวแปร + ข้อสรุปสำคัญ) จัดวางเป็นกริดแน่นเพื่อให้
# ใช้ชี้แจง/นำเสนอได้โดยแทบไม่ต้องเลื่อนหน้าจอ — เหมาะกับการฉายนำเสนอสด ๆ
# ------------------------------------------------------------------------------
elif st.session_state.page == "exec_dashboard":
    st.session_state.setdefault("exec_presentation_mode", False)
    # ----- แสดงผล 2 ระดับตามสิทธิ์ผู้ใช้ -----
    # บุคคลทั่วไป (ยังไม่ได้เข้าสู่ระบบคณะวิจัย) เห็นเฉพาะภาพรวมแนวโน้ม/พยากรณ์ TFP
    # แบบเข้าใจง่าย ไม่พูดถึงศัพท์เชิงเทคนิค (สมมติฐาน/ปัจจัย/ตัวแปร) ส่วนคณะวิจัย
    # ที่ล็อกอินแล้วจะเห็นเพิ่มเติมทุกอย่างที่เป็นข้อมูลเชิงวิชาการสำหรับอ้างอิง
    # นำเสนอผู้บริหาร (การ์ดผลสมมติฐาน, สัดส่วนอิทธิพลตัวแปร, ประเด็นเชิงเทคนิค)
    _is_research = st.session_state.research_authenticated

    # ----- CSS เฉพาะหน้านี้: ย่อ padding/ระยะห่าง/ขนาดตัวอักษรของการ์ดต่าง ๆ ให้แน่น
    # ขึ้นกว่าหน้าอื่นในแอป (ซึ่งเว้นระยะไว้กว้างเพื่ออ่านทีละหมวด) เพื่อให้เนื้อหา
    # ทั้งหมดของหน้านี้อัดพอดีในจอเดียวมากที่สุดสำหรับโหมดนำเสนอ -----
    st.markdown(
        """
        <style>
        /* ============================================================
           โทนพรีเมียมสำหรับ "แดชบอร์ดสำหรับนำเสนอ" — ยังคงความกระชับพอดีจอ
           แต่ยกระดับความหรูด้วยพื้นไล่เฉด, ตัวเลขฟอนต์เซอริฟ, และแถบสี
           เน้นเฉพาะจุดแทนไอคอนพื้นทึบแบบเดิม
           ============================================================ */
        .st-key-exec_dash_wrap .section-card { padding: 14px 22px; margin-bottom: 14px; }
        .st-key-exec_dash_wrap .section-title { gap: 12px; }
        .st-key-exec_dash_wrap .section-num { width: 36px; height: 36px; font-size: 1rem; margin-top: 7px; }
        .st-key-exec_dash_wrap .section-title h3 { font-size: 1.05rem; margin: 0; }
        .st-key-exec_dash_wrap [data-testid="stVerticalBlock"] { gap: 0.55rem; }

        /* ----- แถบหัวเรื่องแบบ hero (แทน topbar เรียบเดิม) ----- */
        .exec-hero {
            position: relative; overflow: hidden; border-radius: 20px;
            padding: 22px 28px; margin-bottom: 14px; color: #fff;
            background-image:
                radial-gradient(560px 220px at 94% 0%, rgba(249,115,22,0.30), transparent 65%),
                linear-gradient(155deg, var(--brand-navy) 0%, #0C1F30 100%);
            box-shadow: 0 20px 44px rgba(11,26,40,0.28), 0 2px 8px rgba(11,26,40,0.16);
            animation: tfp-rise .4s ease both;
        }
        .exec-hero-eyebrow {
            font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
            color: #F6C177;
        }
        .exec-hero h2 {
            font-family: var(--font-elegant); margin: 4px 0 0; font-size: 1.55rem; font-weight: 600;
            color: #fff; letter-spacing: -0.01em;
        }
        .exec-hero .sub {
            margin-top: 6px; font-size: 0.85rem; color: rgba(255,255,255,0.68); max-width: 640px;
            line-height: 1.55;
        }
        .exec-hero .timestamp-pill {
            display: inline-flex; align-items: center; gap: 6px; margin-top: 14px;
            background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.16);
            border-radius: 999px; padding: 5px 13px; font-size: 0.75rem; color: rgba(255,255,255,0.85);
        }

        /* ----- การ์ด KPI พรีเมียม: แถบสีซ้าย + ไอคอนวงกลมโทนอ่อนของสีเน้น ----- */
        .st-key-exec_dash_wrap .metric-card {
            padding: 16px 18px; gap: 14px; border-radius: 14px;
            border-left: 4px solid var(--exec-accent, var(--brand-orange));
        }
        .st-key-exec_dash_wrap .metric-icon {
            width: 42px; height: 42px; font-size: 1.05rem; box-shadow: none;
            background: var(--exec-accent-tint, rgba(249,115,22,0.14)) !important;
            color: var(--exec-accent, var(--brand-orange)) !important;
        }
        .st-key-exec_dash_wrap .metric-value { font-family: var(--font-elegant); font-size: 1.42rem; }
        .st-key-exec_dash_wrap .metric-label { font-size: 0.74rem; }

        .st-key-exec_dash_wrap .nxpo-summary-card { padding: 16px 20px 15px; }
        .st-key-exec_dash_wrap .nxpo-summary-card .value { font-size: 1.15rem; font-family: var(--font-elegant); line-height: 1.35; }
        .st-key-exec_dash_wrap .nxpo-summary-card .label { font-size: 0.76rem; margin-bottom: 4px; }
        .st-key-exec_dash_wrap .nxpo-summary-card .from-label { font-size: 0.74rem; }

        /* ----- แถบเครื่องมือมุมขวา: ปุ่ม "กลับ" + สลับ "โหมดนำเสนอ" อยู่ใกล้กัน -----
           เดิมเป็นปุ่มพื้นขาวทึบ + ตัวหนังสือสีกรมท่าอ่อน (โทนสำหรับพื้นหลังสว่าง)
           ไปวางทับบนการ์ด hero พื้นกรมท่าเข้ม เลยดูเหมือนหลุดมาจากคนละที่ ไม่กลืนกับ
           ธีมมืดของ hero เลย — เปลี่ยนเป็นสไตล์กระจกฝ้า (โปร่งแสงขาวจาง ๆ + ตัวหนังสือ
           สีขาว) แบบเดียวกับ timestamp-pill ที่อยู่ในการ์ดเดียวกัน ให้เป็นชุดเดียวกัน */
        .st-key-exec_dash_wrap .st-key-exec_back_to_forecast button {
            border: 1px solid rgba(255,255,255,0.45) !important;
            background: rgba(255,255,255,0.16) !important;
            color: #FFFFFF !important;
            font-weight: 600 !important; font-size: 0.86rem !important;
            border-radius: 999px !important; box-shadow: none !important;
            transition: all .15s ease !important; white-space: nowrap !important;
            padding: 9px 16px !important; height: 100% !important;
            display: flex !important; align-items: center !important; justify-content: center !important;
            line-height: 1 !important;
        }
        .st-key-exec_dash_wrap .st-key-exec_back_to_forecast button:hover {
            border-color: rgba(255,255,255,0.65) !important; background: rgba(255,255,255,0.26) !important;
            color: #FFFFFF !important; transform: translateY(-1px);
        }
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle {
            display: flex; align-items: center; justify-content: center; gap: 8px;
            background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.45);
            border-radius: 999px; padding: 9px 16px; box-shadow: none; white-space: nowrap; height: 100%;
        }
        /* พยายามจัดกึ่งกลางแนวตั้งของสวิตช์เทียบกับปุ่ม "กลับ" มาหลายรอบแล้วยังไม่
           ตรงเป๊ะ สงสัยว่า Streamlit/BaseWeb ใส่ margin/padding แฝงไว้ในชั้นใดชั้น
           หนึ่งที่ยังไม่เจอ — รอบนี้เคลียร์ margin/padding ทุกชั้นภายในกล่องนี้แบบ
           ครอบคลุมทีเดียว (wildcard) แทนการไล่เดาทีละชั้น เพื่อตัดปัญหาที่ต้นตอ */
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle * {
            margin: 0 !important; padding: 0 !important; box-sizing: border-box !important;
        }
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle label,
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle [data-baseweb="checkbox"],
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle [role="switch"] {
            display: flex !important; align-items: center !important; height: auto !important;
        }
        /* ปรับตำแหน่งขึ้น 2px ตามที่ขอ (แบบเจาะจงตรงๆ แทนการเดา CSS ต่อไปเรื่อยๆ) */
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle [role="switch"] {
            position: relative; top: -2px;
        }
        /* พยายามลบพื้นหลังกล่องเทาที่ Streamlit ใส่มากับป้ายชื่อ/ไอคอนคำแนะนำของ
           st.toggle มาหลายรอบแล้วไม่หลุดจริงสักที (อาจเป็น container ชั้นอื่นที่ยัง
           ไม่เจอ) — เปลี่ยนวิธีให้เด็ดขาดแทน: ซ่อนป้ายชื่อ + ไอคอน "?" ของ Streamlit
           เองไปเลย (label_visibility="collapsed" ในโค้ด Python) แล้ววาดคำว่า
           "โหมดนำเสนอ" ขึ้นเองด้วย CSS content: ล้วน ๆ ไม่ผ่านการเรนเดอร์ของ
           Streamlit อีกต่อไป จึงไม่มีทางมีกล่องพื้นหลังแปลกปลอมได้อีก */
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle [data-testid="stWidgetLabel"] {
            display: none !important;
        }
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle::after {
            content: "โหมดนำเสนอ"; font-size: 0.86rem; font-weight: 600;
            color: #FFFFFF; white-space: nowrap; line-height: 1;
        }
        /* แทร็กของสวิตช์ตอน "ปิด" (ยังไม่ได้เปิดโหมดนำเสนอ) ให้สว่างขึ้นด้วย
           เพราะสีเทาเข้มค่าเริ่มต้นของ Streamlit จะกลืนไปกับพื้นกรมท่าเข้มจนมองไม่เห็น
           ว่ามีสวิตช์อยู่ตรงนี้ */
        .st-key-exec_dash_wrap .st-key-exec_presentation_toggle [data-baseweb="checkbox"] div {
            background-color: rgba(255,255,255,0.35) !important;
        }
        /* ----- ปุ่มสลับ Dark Mode ใหม่ — ใช้สูตร/เทคนิคเดียวกับ "โหมดนำเสนอ" ทุก
           อย่าง (ซ่อนป้ายชื่อ Streamlit เอง วาดข้อความเองด้วย ::after กันกล่องเทา
           แปลกปลอม, เคลียร์ margin/padding ทุกชั้น, ขยับสวิตช์ขึ้น 2px ให้ตรงแนว) */
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle {
            display: flex; align-items: center; justify-content: center; gap: 8px;
            background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.45);
            border-radius: 999px; padding: 9px 16px; box-shadow: none; white-space: nowrap; height: 100%;
        }
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle * {
            margin: 0 !important; padding: 0 !important; box-sizing: border-box !important;
        }
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle label,
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle [data-baseweb="checkbox"],
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle [role="switch"] {
            display: flex !important; align-items: center !important; height: auto !important;
        }
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle [role="switch"] {
            position: relative; top: -2px;
        }
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle [data-testid="stWidgetLabel"] {
            display: none !important;
        }
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle::after {
            content: "🌙 Dark Mode"; font-size: 0.86rem; font-weight: 600;
            color: #FFFFFF; white-space: nowrap; line-height: 1;
        }
        .st-key-exec_dash_wrap .st-key-exec_dark_mode_toggle [data-baseweb="checkbox"] div {
            background-color: rgba(255,255,255,0.35) !important;
        }
        /* ตารางพยากรณ์รายปีในแดชบอร์ดสรุปสำหรับนำเสนอ — เดิมแถวสูง/ตัวหนังสือใหญ่
           เท่ากับตารางทั่วไป ทำให้ตารางนี้ดูใหญ่/เด่นเกินไปเมื่อเทียบกับการ์ดอื่นๆ
           รอบๆ ในเลย์เอาต์ 2 คอลัมน์ — บีบ padding ของเซลล์ให้แน่นขึ้นเฉพาะจุดนี้
           (ไม่กระทบตาราง .tfp-table ที่ใช้อยู่ที่อื่นในแอป) ให้บาลานซ์กับส่วนอื่น */
        .compact-fc-table td, .compact-fc-table th { padding: 6px 8px !important; }
        /* ----- ฝังปุ่ม "กลับ" + สลับ "โหมดนำเสนอ" ไว้ในมุมขวาบนของแถบ hero สีกรมท่า
           เอง แทนที่จะปล่อยให้ลอยเป็นแถวแยกใต้ hero ซึ่งทำให้เกิดช่องว่างแปลก ๆ
           ระหว่าง hero กับแถวปุ่ม (เห็นได้ชัดตอนจอกว้าง) — ใช้ position:absolute
           วางทับมุมขวาบนของกล่อง exec_dash_wrap แทน (ซึ่ง .exec-hero เป็นลูกตัวแรก
           อยู่แล้ว จึงพอดีกับมุมขวาบนของ hero เป๊ะ) */
        .st-key-exec_dash_wrap { position: relative; }
        .st-key-exec_dash_wrap div[data-testid="stHorizontalBlock"]:has(.st-key-exec_back_to_forecast) {
            position: absolute; top: 22px; right: 28px; width: auto; z-index: 5;
        }
        .st-key-exec_dash_wrap div[data-testid="stHorizontalBlock"]:has(.st-key-exec_back_to_forecast) [data-testid="stColumn"] {
            width: auto !important; min-width: 0 !important; flex: 0 0 auto !important;
        }
        .st-key-exec_dash_wrap .st-key-exec_back_to_forecast,
        .st-key-exec_dash_wrap .st-key-exec_back_to_forecast > div {
            height: 100%;
        }

        /* ----- ลิสต์ "ประเด็นสำคัญ" แบบพรีเมียม (เลขวงกลมเซอริฟ + เส้นประคั่น) ----- */
        .exec-insight-item {
            display: flex; gap: 12px; align-items: flex-start; padding: 7px 0;
            border-bottom: 1px dashed var(--card-border); font-size: 0.86rem;
            color: var(--brand-navy); line-height: 1.55;
        }
        .exec-insight-item:last-child { border-bottom: none; }
        .exec-insight-num {
            flex-shrink: 0; width: 22px; height: 22px; border-radius: 50%; margin-top: 1px;
            border: 1.5px solid var(--brand-orange); color: var(--brand-orange-dark);
            font-family: var(--font-elegant); font-weight: 700; font-size: 0.72rem;
            display: flex; align-items: center; justify-content: center;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="exec_dash_wrap"):
        st.markdown(
            f'<div class="exec-hero">'
            f'<div class="exec-hero-eyebrow">{icon("sparkle", 12, 2)} Presentation Dashboard</div>'
            f'<h2>แดชบอร์ดสรุปสำหรับนำเสนอ</h2>'
            f'<div class="sub">ภาพรวมผลพยากรณ์ผลิตภาพปัจจัยการผลิตรวม (TFP) '
            f'จัดวางเป็นสรุปหน้าเดียวสำหรับการนำเสนอ</div>'
            f'<div class="timestamp-pill">{icon("clock", 12, 2)} ข้อมูลล่าสุด {thai_timestamp()}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        _btn_back, _btn_present, _btn_dark = st.columns([1, 1.7, 1.5], gap="small")
        with _btn_back:
            if st.button("← กลับ", key="exec_back_to_forecast", use_container_width=True):
                st.session_state.page = "forecast"
                st.rerun()
        with _btn_present:
            # label_visibility="collapsed" + ไม่ใช้ help= อีกต่อไป: ซ่อนป้ายชื่อ/
            # ไอคอน "?" ที่ Streamlit เรนเดอร์เอง (ตัวการของกล่องพื้นหลังเทาที่แก้
            # ไม่หายสักที) แล้ววาดคำว่า "โหมดนำเสนอ" ขึ้นเองด้วย CSS ::after แทน
            # (ดูสไตล์ .st-key-exec_presentation_toggle::after ด้านบน)
            st.session_state.exec_presentation_mode = st.toggle(
                "โหมดนำเสนอ", value=st.session_state.exec_presentation_mode,
                key="exec_presentation_toggle", label_visibility="collapsed",
            )
        with _btn_dark:
            st.session_state.setdefault("exec_dark_mode", False)
            st.session_state.exec_dark_mode = st.toggle(
                "Dark Mode", value=st.session_state.exec_dark_mode,
                key="exec_dark_mode_toggle", label_visibility="collapsed",
            )

        if st.session_state.exec_presentation_mode:
            st.markdown(
                '<style>[data-testid="stSidebar"], [data-testid="collapsedControl"] {display:none;}</style>',
                unsafe_allow_html=True,
            )

        if st.session_state.exec_dark_mode:
            # ----- Dark Mode สำหรับหน้าแดชบอร์ดสรุปนี้โดยเฉพาะ -----
            # เดิม hero เป็นกรมท่าเข้มอยู่แล้ว แต่การ์ดเนื้อหาด้านล่าง (KPI, กราฟ,
            # ตาราง) ยังเป็นพื้นขาวทั้งหมด — โหมดนี้พลิกให้การ์ดเนื้อหาเป็นกรมท่า
            # เข้มด้วย ให้เข้าธีมเดียวกับ hero ทั้งหน้า เหมาะกับการนำเสนอในห้องมืด/
            # โปรเจกเตอร์ (สโคปเฉพาะ .st-key-exec_dash_wrap เท่านั้น ไม่กระทบหน้าอื่น
            # ในแอปเลย แม้จะใช้คลาสเดียวกัน เช่น .metric-card ก็ตาม)
            st.markdown(
                """
                <style>
                .st-key-exec_dash_wrap { background: linear-gradient(180deg, #0B1A28 0%, #142C42 100%);
                    border-radius: 24px; padding: 18px; }
                .st-key-exec_dash_wrap .metric-card, .st-key-exec_dash_wrap .section-card {
                    background: linear-gradient(180deg, #EDF0F3 0%, #E1E5EA 100%) !important;
                    border-color: rgba(255,255,255,0.14) !important;
                    box-shadow: 0 10px 26px rgba(0,0,0,0.3) !important;
                }
                /* เปลี่ยนเฉพาะสีขอบซ้าย (border-left) เป็นขาวตามที่ขอ โดยไม่แตะ
                   ตัวแปร --exec-accent เดิม เพราะตัวแปรเดียวกันนี้ยังถูกใช้กำหนดสี
                   ไอคอนตรงกลางวงกลมด้วย (.metric-icon) ถ้าเปลี่ยนรวมกัน ไอคอนจะ
                   กลายเป็นสีขาวจนจมหายไปกับพื้นวงกลมสีอ่อนที่เป็นโทนเดียวกัน */
                .st-key-exec_dash_wrap .metric-card { border-left-color: #FFFFFF !important; }
                .st-key-exec_dash_wrap .section-card::before { background-image: none !important; background: #FFFFFF !important; opacity: 0.9 !important; }
                .st-key-exec_dash_wrap .metric-value,
                .st-key-exec_dash_wrap .section-title-text h3,
                .st-key-exec_dash_wrap .exec-insight-item { color: var(--brand-navy) !important; }
                .st-key-exec_dash_wrap .metric-label,
                .st-key-exec_dash_wrap p { color: var(--brand-navy-soft) !important; }
                .st-key-exec_dash_wrap .tfp-table-cream { background: #EDF0F3 !important;
                    border-color: rgba(255,255,255,0.14) !important; }
                .st-key-exec_dash_wrap .tfp-table-cream th { background-image: none !important; background: #FFFFFF !important; color: var(--brand-navy) !important; }
                .st-key-exec_dash_wrap .tfp-table-cream td { color: var(--brand-navy-soft) !important;
                    background: transparent !important; border-color: rgba(0,0,0,0.08) !important; }
                .st-key-exec_dash_wrap .tfp-table-cream td:first-child { color: var(--brand-navy) !important; }
                .st-key-exec_dash_wrap .tfp-table-cream tr:nth-child(even) td { background: rgba(0,0,0,0.03) !important; }
                .st-key-exec_dash_wrap .tfp-table-cream tr:hover td { background: rgba(0,0,0,0.06) !important; }
                /* กราฟ/แถวข้อมูลจริงยังใช้พื้นสว่างของตัวเองต่อไปโดยตั้งใจ (เหมือน
                   แผงกระจกสว่างวางอยู่บนพื้นเข้ม) เพราะการพลิกสีกราฟ Altair ทั้งชุด
                   (เส้น/แกน/legend) มีความเสี่ยงสูงที่จะอ่านยากลงแทน จึงเว้นไว้ */
                </style>
                """,
                unsafe_allow_html=True,
            )

        if not result_ready:
            st.info("คลิกเพื่อดึงข้อมูลอัตโนมัติจากแถบด้านซ้ายก่อนเพื่อสร้างแดชบอร์ดสรุปนี้")
        else:
            tfp_series = model_df[DEP_VAR].dropna().sort_index()
            if tfp_series.empty:
                st.info("ไม่พบข้อมูล TFP ในชุดข้อมูลที่ดึงมา")
            else:
                MIN_POINTS_FOR_ARIMA = 8
                # ใช้จำนวนปีพยากรณ์ตามที่ตั้งไว้ในหน้า "พยากรณ์ TFP" (ถ้ายังไม่เคยตั้ง
                # ใช้ค่าเริ่มต้น 5 ปี เหมือนกับ slider เริ่มต้นของหน้านั้น)
                horizon = int(st.session_state.get("exec_dash_horizon", st.session_state.get("tfp_forecast_horizon", 5)))
                last_val = float(tfp_series.iloc[-1])
                last_year = int(tfp_series.index.max())
                prev_val = float(tfp_series.iloc[-2]) if len(tfp_series) > 1 else None
                yoy = ((last_val / prev_val) - 1) * 100 if prev_val else None

                # อัตราการเติบโตเฉลี่ยของ TFP ย้อนหลัง (เฉลี่ย YoY ของข้อมูลจริงในช่วง
                # สูงสุด 5 ปีล่าสุด) — ใช้เทียบภาพให้เห็นว่าที่ผ่านมาโตเฉลี่ยเท่าไร
                # หมายเหตุ: นี่คือค่าเฉลี่ยการเติบโตของ "ข้อมูลจริงในอดีต" (Historical
                # Average Growth) คนละตัวกับ cagr/growth_total ด้านล่างซึ่งเป็นอัตรา
                # การเติบโตที่ "พยากรณ์" ไปข้างหน้าจากแบบจำลอง ARIMA — ตัวเลขทั้งสอง
                # ชุดนี้แตกต่างกันได้ตามธรรมชาติ (คนละช่วงเวลา คนละที่มา) จึงต้อง
                # ตั้งชื่อป้ายกำกับให้ชัดเจนว่าตัวไหนเป็นอดีต ตัวไหนเป็นค่าพยากรณ์
                # เพื่อไม่ให้ผู้ใช้เข้าใจผิดว่าเป็นตัวเลขชุดเดียวกัน
                _hist_n = min(5, len(tfp_series) - 1)
                if _hist_n > 0:
                    _hist_yoy = tfp_series.pct_change().dropna().iloc[-_hist_n:] * 100
                    hist_avg_growth = float(_hist_yoy.mean())
                else:
                    hist_avg_growth = None

                _has_forecast = len(tfp_series) >= MIN_POINTS_FOR_ARIMA
                if _has_forecast:
                    with st.spinner("กำลังพยากรณ์ตามช่วงปีที่ตั้งไว้..."):
                        forecast_df, arima_order = _auto_arima_forecast(tfp_series, horizon)
                    fc_year = int(forecast_df.index.max())
                    fc_final = float(forecast_df.loc[fc_year, "mean"])
                    growth_total = ((fc_final / last_val) - 1) * 100 if last_val else 0.0
                    cagr = (((fc_final / last_val) ** (1 / horizon)) - 1) * 100 if last_val and horizon > 0 else 0.0

                # ----- ดึงสมมติฐาน "สมมติตัวแปรเปลี่ยนแปลง" ที่ตั้งไว้ในหน้าพยากรณ์ TFP
                # (ถ้ามี) มาคำนวณผลกระทบต่อ TFP ซ้ำ เพื่อโชว์เป็นการ์ดสมมติฐานเชิงนโยบาย
                # หมายเหตุ: เป็นการประมาณอย่างง่ายจากค่าความยืดหยุ่นของสมการระยะยาว
                # แยกจากแบบจำลอง ARIMA ข้างต้น (คนละวิธีคำนวณ) จึงใช้เป็นภาพประกอบ
                # เชิงนโยบายเท่านั้น ไม่ใช่การพยากรณ์ร่วมสมการเดียวกัน -----
                scenario_var = st.session_state.get("exec_dash_chosen_var")
                scenario_pct_effect = None
                scenario_shock = None
                if scenario_var and scenario_var in lr_raw_map:
                    scenario_shock = st.session_state.get(f"impact_shock_{scenario_var}")
                    if scenario_shock is not None:
                        _coef = lr_raw_map[scenario_var]["coef"]
                        if scenario_var.startswith("ln_"):
                            scenario_pct_effect = _coef * scenario_shock
                        else:
                            scenario_pct_effect = (math.exp(_coef * scenario_shock) - 1) * 100

                st.caption(
                    f"ข้อมูลล่าสุด: {thai_timestamp()} • ปีข้อมูล {tfp_series.index.min()}–{tfp_series.index.max()} "
                    f"• ช่วงพยากรณ์ {horizon} ปีข้างหน้า (ตั้งค่าจากหน้า \"พยากรณ์ TFP\")"
                )

                # ================= แถว 1: การ์ด KPI สรุป 4 ใบ =================
                # accent เป็นสี hex จริง (ไม่ใช้ var(...)) เพื่อให้ต่อท้ายรหัสความโปร่งใส
                # 2 หลัก (เช่น "1F" ~ 12%) แล้วได้สีพื้นหลังไอคอนโทนอ่อนแบบ tint ของสีเน้นนั้น ๆ
                # เดิมใช้สีรุ้ง 4 สี (ส้ม/ฟ้าสด/กรมท่า/เขียวสด) เหมือนที่เคยแก้ในหน้า
                # Dashboard หลักไปแล้ว — สลับให้เหลือแค่ 2 เฉดของแบรนด์เอง (ส้ม/กรมท่า)
                # ให้เข้าธีมเดียวกันทั้งแอป
                def _exec_kpi(accent, icon_svg, value, label):
                    return (
                        f'<div class="metric-card" style="--exec-accent:{accent};--exec-accent-tint:{accent}1F;">'
                        f'<div class="metric-icon">{icon_svg}</div>'
                        f'<div><div class="metric-value">{value}</div><div class="metric-label">{label}</div></div></div>'
                    )

                kpi_cols = st.columns(4)
                with kpi_cols[0]:
                    yoy_text = f"{yoy:+.1f}%" if yoy is not None else "-"
                    st.markdown(
                        _exec_kpi("#F97316", icon("bars", 18, 1.8), f"{last_val:,.2f}",
                                  f"TFP ล่าสุด (ปี {last_year}) {yoy_text} เทียบปีก่อน"),
                        unsafe_allow_html=True,
                    )
                with kpi_cols[1]:
                    if _has_forecast:
                        st.markdown(
                            _exec_kpi("#16324A", icon("clock", 18, 1.8), f"{fc_final:,.2f}",
                                      f"ค่าพยากรณ์ TFP (ปี {fc_year})"),
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(_exec_kpi("#16324A", icon("clock", 18, 1.8), "-",
                                               "ข้อมูลยังไม่พอสำหรับพยากรณ์"), unsafe_allow_html=True)
                with kpi_cols[2]:
                    hg_text = f"{hist_avg_growth:+.2f}%" if hist_avg_growth is not None else "-"
                    st.markdown(
                        _exec_kpi("#F97316", icon("trend-up", 18, 1.8), hg_text,
                                  f"อัตราเติบโตเฉลี่ยของข้อมูลจริงย้อนหลัง {_hist_n} ปี (ไม่ใช่ค่าพยากรณ์)"),
                        unsafe_allow_html=True,
                    )
                with kpi_cols[3]:
                    if not _is_research:
                        # มุมมองบุคคลทั่วไป: ไม่พูดถึงสมมติฐาน/ตัวแปร — แสดงจำนวนปี
                        # ข้อมูลย้อนหลังที่ใช้วิเคราะห์แทน (เข้าใจง่าย เป็นกลาง)
                        st.markdown(
                            _exec_kpi("#16324A", icon("database", 18, 1.8), f"{len(tfp_series)} ปี",
                                      f"ข้อมูลย้อนหลังที่ใช้วิเคราะห์ ({tfp_series.index.min()}–{tfp_series.index.max()})"),
                            unsafe_allow_html=True,
                        )
                    elif scenario_pct_effect is not None:
                        st.markdown(
                            _exec_kpi("#16324A", icon("bulb", 18, 1.8), f"{scenario_pct_effect:+.2f}%",
                                      f"สมมติฐาน: {_var_full_name(scenario_var)} เปลี่ยน {scenario_shock:g}"
                                      f"{'%' if scenario_var.startswith('ln_') else ''}"),
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            _exec_kpi("#16324A", icon("bulb", 18, 1.8), f"{n_pass}/{n_pass + n_watch + n_fail}",
                                      "ผ่านเกณฑ์ข้อสมมติฐาน (ยังไม่ได้ตั้งสมมติฐานตัวแปร)"),
                            unsafe_allow_html=True,
                        )
                st.write("")

                # ================= แถว 2: กราฟหลัก (ซ้าย) + ตารางพยากรณ์ย่อ/สรุป (ขวา) =================
                col_main, col_side = st.columns([1.7, 1], gap="medium")
                with col_main:
                    st.markdown(
                        f'<div class="section-card"><div class="section-title">'
                        f'<div class="section-num">{icon("trend-up", 16, 2)}</div>'
                        f'<div class="section-title-text"><h3>แนวโน้ม TFP และพยากรณ์ {horizon} ปีข้างหน้า</h3>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
                    if _has_forecast:
                        _nice_line_chart_with_forecast(
                            tfp_series, forecast_df, color="#F97316", forecast_color="#2F6FED", height=230,
                        )
                        if _is_research and scenario_pct_effect is not None:
                            _scn_final = fc_final * (1 + scenario_pct_effect / 100)
                            st.markdown(
                                f'<div style="font-size:0.78rem;color:var(--brand-navy-soft);'
                                f'line-height:1.5;margin-top:2px;">'
                                f'💡 ถ้าเป็นไปตามสมมติฐานด้านบน TFP ปี {fc_year} อาจขยับไปที่ราว '
                                f'<b style="color:var(--brand-navy);">{_scn_final:,.2f}</b> '
                                f'(เทียบกับพยากรณ์ฐาน {fc_final:,.2f}) — เป็นภาพประกอบเชิงนโยบายอย่างง่าย '
                                f'จากค่าความยืดหยุ่นของสมการระยะยาว ไม่ใช่การพยากรณ์ร่วมกับแบบจำลอง ARIMA โดยตรง</div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        _nice_line_chart(tfp_series, color="#F97316", height=230)
                        st.info(f"ข้อมูลมีเพียง {len(tfp_series)} ปี ยังไม่พอสำหรับพยากรณ์ด้วย ARIMA")
                    if _has_forecast:
                        st.markdown(
                            f'<div style="font-size:0.78rem;color:var(--brand-navy-soft);'
                            f'line-height:1.6;margin-top:10px;padding-top:10px;'
                            f'border-top:1px dashed var(--card-border);">'
                            f'เส้นสีส้มแสดงค่า TFP ที่สังเกตได้จริงถึงปี {last_year} '
                            f'(ค่าล่าสุด {last_val:,.2f}) ส่วนเส้นสีน้ำเงินแสดงค่าพยากรณ์จากแบบจำลอง ARIMA '
                            f'จนถึงปี {fc_year} พร้อมแถบสีแสดงช่วงความเชื่อมั่น 95% '
                            f'ซึ่งสะท้อนระดับความไม่แน่นอนของค่าพยากรณ์ที่เพิ่มขึ้นตามระยะเวลาการพยากรณ์</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown('</div>', unsafe_allow_html=True)

                with col_side:
                    if _has_forecast:
                        st.markdown(
                            f'<div class="section-card"><div class="section-title">'
                            f'<div class="section-num">{icon("calendar", 16, 2)}</div>'
                            f'<div class="section-title-text"><h3>พยากรณ์ TFP รายปี</h3></div></div>',
                            unsafe_allow_html=True,
                        )
                        # แสดงผลพยากรณ์ครบทุกปีตามช่วงพยากรณ์ที่ตั้งไว้ (ไม่ตัดเหลือ
                        # แค่ 4 ปีแรกเหมือนเดิม) — ถ้ายาวเกินจะมี scroll ในกรอบแทน
                        # เพื่อไม่ให้หน้าแดชบอร์ดยาวเกินความจำเป็น
                        _fc_head = forecast_df["mean"]
                        _fc_rows_html = ""
                        _prev = last_val
                        for _yr, _val in _fc_head.items():
                            _g = ((_val / _prev) - 1) * 100 if _prev else 0.0
                            _prev = _val
                            _fc_rows_html += (
                                f'<tr><td>{int(_yr)}</td><td>{_val:,.2f}</td>'
                                f'<td style="color:{"var(--green)" if _g >= 0 else "var(--red)"};">{_g:+.2f}%</td></tr>'
                            )
                        st.markdown(
                            f'<div class="compact-fc-table" style="overflow-x:auto;max-height:172px;overflow-y:auto;">'
                            f'<table class="tfp-table" style="font-size:0.8rem;">'
                            f'<thead><tr><th>ปี</th><th>ค่าพยากรณ์</th><th>อัตราเติบโต</th></tr></thead>'
                            f'<tbody>{_fc_rows_html}</tbody></table></div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown('</div>', unsafe_allow_html=True)

                        _trend_icon = "trend-up" if growth_total >= 0 else "trend-down"
                        _trend_word = "เพิ่มขึ้น" if growth_total >= 0 else "ลดลง"
                        st.markdown(
                            f'<div class="nxpo-summary-card">'
                            f'<div class="label">{icon("sparkle", 12, 2)} สรุปจากแบบจำลอง</div>'
                            f'<div class="value">TFP มีแนวโน้ม{_trend_word}เฉลี่ยประมาณ {cagr:+.1f}% ต่อปี</div>'
                            f'<div class="from-label">ในช่วง {horizon} ปีข้างหน้า '
                            f'<span class="growth-badge">{icon(_trend_icon, 12, 2)} {growth_total:+.1f}%</span></div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                st.write("")

                # ================= แถว 3: สัดส่วนอิทธิพลตัวแปร (ซ้าย) + คุณภาพแบบจำลอง/ข้อสรุป (ขวา) =================
                # เฉพาะคณะวิจัยที่ล็อกอินแล้วเท่านั้นที่เห็นกราฟสัดส่วนอิทธิพลของตัวแปร
                # (เป็นข้อมูลเชิงวิชาการ) — บุคคลทั่วไปจะเห็นเฉพาะ "ประเด็นสำคัญ" แบบ
                # เข้าใจง่าย ไม่พูดถึงตัวแปร/สมมติฐาน โดยขยายเต็มความกว้างแทน
                infl_df = None
                if _is_research:
                    col_infl, col_notes = st.columns([1.3, 1], gap="medium")
                    with col_infl:
                        st.markdown(
                            f'<div class="section-card"><div class="section-title">'
                            f'<div class="section-num">{icon("bars", 16, 1.8)}</div>'
                            f'<div class="section-title-text"><h3>ตัวแปรที่มีอิทธิพลต่อ TFP มากที่สุด</h3></div></div>',
                            unsafe_allow_html=True,
                        )
                        infl_df, infl_err = _compute_influence_df(model_df, dep_ln, active_lr_vars, lr_raw_map)
                        if infl_df is None:
                            st.info(infl_err)
                        else:
                            _top_infl = infl_df.head(4)
                            dir_scale = alt.Scale(
                                domain=["หนุนเสริม TFP (+)", "ฉุดรั้ง TFP (−)"], range=["#16A34A", "#EF4444"],
                            )
                            bars = alt.Chart(_top_infl).mark_bar(
                                cornerRadiusTopRight=5, cornerRadiusBottomRight=5, height=16,
                            ).encode(
                                x=alt.X("สัดส่วน (%):Q", title=None, axis=alt.Axis(grid=False, domain=False,
                                                                                    labelFontSize=10, labelColor="#5B6B7C")),
                                y=alt.Y("label:N", sort="-x", title=None,
                                        axis=alt.Axis(domain=False, labelFontSize=11, labelColor="#16324A", labelLimit=220)),
                                color=alt.Color("ทิศทาง:N", scale=dir_scale, legend=None),
                                tooltip=[alt.Tooltip("label:N", title="ตัวแปร"),
                                         alt.Tooltip("สัดส่วน (%):Q", title="สัดส่วน", format=".1f")],
                            )
                            chart = (
                                bars.properties(height=max(120, 34 * len(_top_infl)),
                                                padding={"left": 5, "right": 5, "top": 2, "bottom": 2})
                                .configure_view(strokeWidth=0)
                                .configure_axis(labelFont=FONT_FAMILY)
                            )
                            st.altair_chart(chart, use_container_width=True)
                        st.markdown('</div>', unsafe_allow_html=True)
                else:
                    col_notes = st.container()

                with col_notes:
                    _n_total = n_pass + n_watch + n_fail
                    _top_var_label = infl_df.iloc[0]["label"] if infl_df is not None and not infl_df.empty else None
                    _insight_lines = []
                    if _has_forecast:
                        _insight_lines.append(
                            f"TFP มีแนวโน้ม{'เพิ่มขึ้น' if growth_total >= 0 else 'ลดลง'}ต่อเนื่องถึงปี {fc_year}"
                        )
                    # เส้นข้อมูลเชิงวิชาการ (ตัวแปร/สมมติฐาน) แสดงเฉพาะคณะวิจัยที่ล็อกอินแล้ว
                    if _is_research:
                        if _top_var_label:
                            _insight_lines.append(f"'{_top_var_label}' เป็นตัวแปรที่มีอิทธิพลต่อ TFP มากที่สุดในสมการปัจจุบัน")
                        _insight_lines.append(
                            f"แบบจำลองผ่านเกณฑ์ข้อสมมติฐาน {n_pass} จาก {_n_total} รายการ"
                            + (" — ควรตีความผลด้วยความระมัดระวัง" if n_fail > 0 else "")
                        )
                        if scenario_pct_effect is not None:
                            _insight_lines.append(
                                f"สมมติฐานที่ตั้งไว้ ({_var_full_name(scenario_var)} เปลี่ยน {scenario_shock:g}"
                                f"{'%' if scenario_var.startswith('ln_') else ''}) "
                                f"อาจส่งผลต่อ TFP ประมาณ {scenario_pct_effect:+.2f}%"
                            )
                    else:
                        _insight_lines.append(
                            "ระบบวิเคราะห์ด้วยแบบจำลองเศรษฐมิติ ARIMA จากข้อมูลผลิตภาพย้อนหลังของประเทศไทย"
                        )
                    st.markdown(
                        f'<div class="section-card"><div class="section-title" style="margin-bottom:6px;">'
                        f'<div class="section-num">{icon("bulb", 16, 1.8)}</div>'
                        f'<div class="section-title-text"><h3>ประเด็นสำคัญ</h3></div></div>'
                        + "".join(
                            f'<div class="exec-insight-item"><div class="exec-insight-num">{i+1}</div>'
                            f'<div>{line}</div></div>'
                            for i, line in enumerate(_insight_lines)
                        )
                        + '</div>',
                        unsafe_allow_html=True,
                    )

# ------------------------------------------------------------------------------
# หน้า "ทำความรู้จักตัวแปร" — ตารางข้อมูลที่ใช้จริงในโมเดล + คำอธิบายตัวแปรแต่ละตัว
# ------------------------------------------------------------------------------
elif st.session_state.page == "data_vars":
    st.markdown(
        f'<div class="nxpo-topbar"><div class="nxpo-topbar-left">'
        f'<div class="nxpo-topbar-logo">{icon("database", 22, 2)}</div>'
        f'<div class="nxpo-topbar-title"><h2>ทำความรู้จักตัวแปร</h2>'
        f'<span class="eyebrow">Variable Guide</span></div></div></div>',
        unsafe_allow_html=True,
    )

    # หมายเหตุ: หน้านี้ปรับให้เป็นหน้า "ทำความรู้จักตัวแปร" สำหรับผู้ที่สนใจศึกษา
    # ไม่แสดงตารางข้อมูลดิบ/ตัวเลขรายปีใด ๆ อีกต่อไป เนื่องจากถือเป็นข้อมูลที่มี
    # ความอ่อนไหว — เนื้อหาความหมาย กลุ่มตัวแปร และผลการศึกษาอ้างอิงจากรายงานวิจัย
    # ต้นทางของโครงการ (อ้างอิงไว้ท้ายหน้า) ไม่ใช่ตัวเลขจากชุดข้อมูลที่ดึงเข้าระบบจริง
    #
    # ----- ดีไซน์ใหม่ (โฉมเรียบหรู) -----
    # เปลี่ยนจากการ์ดสีสันจัด (พื้นหลังหลายสีตามกลุ่ม + ป้ายสีทึบ) มาเป็นโทนเดียว
    # กับธีมหลักของแอป (ขาว/ครีม + กรมท่า/ส้มเป็นจุดเน้น), จัดตัวแปรเป็นลิสต์แนวตั้ง
    # คอลัมน์เดียวคั่นด้วยเส้นบาง ๆ แทนกล่องแยกสี เพื่อให้อ่านต่อเนื่องลื่นไหลขึ้น
    st.markdown(
        """
        <style>
        .var-intro {
            background: linear-gradient(180deg, #FFFFFF 0%, #FFFDF9 100%);
            border: 1px solid var(--card-border); border-radius: 20px;
            padding: 26px 30px; margin-bottom: 22px; box-shadow: var(--shadow-soft);
            animation: tfp-rise .4s ease both;
        }
        .var-intro-eyebrow {
            font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
            color: var(--brand-orange-dark); margin: 0 0 8px 0;
        }
        .var-intro h3 {
            font-family: var(--font-elegant); font-size: 1.32rem; font-weight: 600;
            color: var(--brand-navy); margin: 0 0 10px 0; letter-spacing: -0.01em;
        }
        .var-intro p {
            font-size: 0.94rem; color: var(--brand-navy-soft); line-height: 1.75; margin: 0;
            max-width: 80ch;
        }
        .var-stats { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 20px; }
        .var-stat {
            border: 1px solid var(--card-border); border-radius: 12px; padding: 8px 18px;
            background: #FFFFFF; text-align: center; min-width: 92px;
        }
        .var-stat b {
            display: block; font-family: var(--font-elegant); font-size: 1.18rem; color: var(--brand-navy);
        }
        .var-stat span { display: block; font-size: 0.7rem; color: var(--brand-navy-soft); margin-top: 2px; }

        .var-group {
            background: #FFFFFF; border: 1px solid var(--card-border); border-radius: 20px;
            margin-bottom: 22px; box-shadow: var(--shadow-soft); overflow: hidden;
            animation: tfp-rise .45s ease both;
        }
        .var-group-head {
            display: flex; align-items: center; gap: 16px; padding: 20px 28px;
            border-bottom: 1px solid #F0DCB0;
            background: linear-gradient(180deg, #FBF2DD 0%, #F6EFDC 100%);
        }
        .var-group-icon {
            width: 46px; height: 46px; border-radius: 14px; flex-shrink: 0;
            background-image: linear-gradient(155deg, var(--brand-orange), var(--brand-orange-dark));
            color: #fff; display: flex; align-items: center; justify-content: center;
            box-shadow: 0 5px 14px rgba(217,109,15,0.28);
        }
        .var-group-title-wrap { min-width: 0; flex: 1; }
        .var-group-title-wrap h3 {
            font-family: var(--font-elegant); font-size: 1.12rem; font-weight: 600;
            color: var(--brand-navy); margin: 0; letter-spacing: -0.01em; line-height: 1.15;
        }
        .var-group-title-wrap p {
            font-size: 0.85rem; color: var(--brand-navy-soft); margin: -3px 0 0 0; line-height: 1.4;
        }
        .var-group-count {
            flex-shrink: 0; font-size: 0.76rem; font-weight: 700; color: var(--brand-orange-dark);
            background: #FFFFFF; border: 1px solid #F0DCB0; padding: 5px 14px;
            border-radius: 999px; white-space: nowrap;
        }
        .var-list { padding: 4px 28px 6px; }
        .var-item {
            padding: 18px 0 18px 14px; border-bottom: 1px solid #F1ECE1;
            border-left: 3px solid var(--dir-color, transparent); position: relative;
        }
        .var-item:last-child { border-bottom: none; }
        .var-item-top { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 12px; }
        .var-item-name {
            font-family: var(--font-elegant); font-weight: 600; font-size: 1.03rem; color: var(--brand-navy);
        }
        .var-item-code {
            font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.72rem;
            color: var(--brand-navy-soft); background: #F7F4EE; border: 1px solid var(--card-border);
            padding: 1px 8px; border-radius: 6px;
        }
        .var-item-meta {
            font-size: 0.78rem; color: var(--brand-navy-soft); opacity: 0.85; margin: 6px 0 10px 0;
        }
        .var-item-meta .sep { margin: 0 7px; opacity: 0.5; }
        .var-item-row { font-size: 0.92rem; color: var(--brand-navy-soft); line-height: 1.7; margin: 0 0 5px 0; }
        .var-item-row:last-child { margin-bottom: 0; }
        .var-item-row b { color: var(--brand-navy); font-weight: 600; }

        /* ----- ไอเดียเพิ่มความน่าสนใจ 5 อย่างที่เลือกมา -----
           1) แถบสีซ้าย .var-item (ด้านบน) บอกทิศทางผลกระทบ +/- ต่อ TFP
           2) ปุ่ม jump-to ไปหาแต่ละกลุ่ม
           3) แถบสัดส่วน +/- ในหัวกลุ่ม
           4) ป้ายไฮไลต์ตัวแปรอิทธิพลสูงสุดในกลุ่ม
           5) ไอคอนกลุ่มขนาดใหญ่จางๆ เป็นพื้นหลังในหัวกลุ่ม */
        .var-jumpnav { display: flex; flex-wrap: wrap; gap: 8px; margin: -8px 0 22px; }
        .var-jump-pill {
            display: inline-flex; align-items: center; gap: 6px; background: #FFFFFF;
            border: 1px solid var(--card-border); border-radius: 999px; padding: 7px 15px;
            font-size: 0.8rem; font-weight: 600; color: var(--brand-navy-soft);
            text-decoration: none; transition: all .15s ease; box-shadow: var(--shadow-soft);
        }
        .var-jump-pill:hover { border-color: var(--brand-orange); color: var(--brand-orange-dark); }
        .st-key-var_search_box input {
            border-radius: 12px !important; border: 1px solid var(--card-border) !important;
            padding: 10px 16px !important; font-size: 0.9rem !important; background: #FFFFFF !important;
        }
        .st-key-var_search_box input:focus {
            border-color: var(--brand-orange) !important; box-shadow: 0 0 0 3px rgba(249,115,22,0.12) !important;
        }
        .st-key-var_search_box { margin-bottom: 18px; }

        .var-group-head { position: relative; overflow: hidden; }
        /* เดิมวางไอคอนใหญ่ (130px) แบบเลยขอบการ์ดออกไปแล้วหวังให้ overflow:hidden
           ตัดให้พอดี แต่ดูภาพจริงแล้วมันโผล่เลยขอบการ์ดออกไปในพื้นที่ว่างด้านนอก
           (ดูแปลกและรก) แถมไอคอนเส้นบางๆ อย่าง bars/settings พอขยายใหญ่มากก็ไม่
           เหลือเค้าโครงไอคอนเดิมแล้ว (กลายเป็นเส้น/รังสีสุ่มๆ) — ลดขนาดลงมาก
           และวางให้อยู่ในขอบเขตการ์ดเต็มๆ ตั้งแต่แรก ไม่พึ่ง overflow มาช่วยตัดอีก */
        .var-group-head-icon-bg {
            position: absolute; top: 14px; right: 20px; opacity: 0.12;
            color: var(--brand-orange-dark); pointer-events: none;
        }

        .var-group-split {
            display: flex; align-items: center; gap: 8px; margin-top: 6px; flex-shrink: 0;
        }
        .var-split-bar {
            display: flex; width: 64px; height: 6px; border-radius: 999px; overflow: hidden;
            background: #EDE7DA; flex-shrink: 0;
        }
        .var-split-bar .pos { background: var(--green); height: 100%; }
        .var-split-bar .neg { background: var(--red); height: 100%; }
        .var-split-label { font-size: 0.68rem; color: var(--brand-navy-soft); white-space: nowrap; }

        .var-top-badge {
            display: inline-flex; align-items: center; gap: 4px; font-size: 0.68rem; font-weight: 700;
            color: #fff; background: linear-gradient(135deg, var(--brand-orange), var(--brand-orange-dark));
            padding: 2px 9px; border-radius: 999px; white-space: nowrap;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ----- ตรวจทิศทางผลกระทบ +/- ของแต่ละตัวแปร -----
    # ถ้าดึงข้อมูลและรันโมเดลแล้ว (lr_raw_map มีค่า) ใช้ทิศทางจากสัมประสิทธิ์จริง
    # ของสมการระยะยาว (แม่นยำที่สุด) — ถ้ายังไม่ได้ดึงข้อมูล/เป็นตัวแปรระยะสั้นที่ไม่
    # อยู่ในสมการระยะยาว ใช้การอ่านคำบรรยาย "ผลต่อ TFP" แบบข้อความแทน (ประมาณการ)
    _infl_df_vars, _infl_err_vars = (None, None)
    if "gsheet_raw_df" in st.session_state and lr_raw_map:
        try:
            _infl_df_vars, _infl_err_vars = _compute_influence_df(model_df, dep_ln, active_lr_vars, lr_raw_map)
        except Exception:
            _infl_df_vars = None
    _direction_map = {}
    _influence_pct_map = {}
    if _infl_df_vars is not None:
        for _, _r in _infl_df_vars.iterrows():
            _direction_map[_r["code"]] = "pos" if _r["std_beta"] >= 0 else "neg"
            _influence_pct_map[_r["code"]] = _r["สัดส่วน (%)"]

    def _infer_direction_from_text(effect_text: str) -> str:
        """ประมาณทิศทางจากคำบรรยายผลการศึกษา เมื่อยังไม่มีค่าสัมประสิทธิ์จริงจาก
        โมเดล (ยังไม่ได้ดึงข้อมูล) — ดูส่วนระยะยาวก่อนถ้ามี ไม่งั้นดูทั้งข้อความ"""
        segment = effect_text
        if "ระยะยาว" in effect_text:
            segment = effect_text.split("ระยะยาว", 1)[1].split("ระยะสั้น")[0]
        if "เชิงลบ" in segment or "เครื่องหมายลบ" in segment:
            return "neg"
        if "บวก" in segment:
            return "pos"
        return "neutral"

    _dir_color = {"pos": "var(--green)", "neg": "var(--red)", "neutral": "transparent"}


    _group_order = [
        "ปัจจัยนำเข้า (Input)",
        "ผลผลิต (Output)",
        "ปัจจัยแวดล้อมทางเศรษฐกิจ",
        "พจน์ปรับตัวของสมการ",
    ]
    # ----- คำอธิบายกลุ่มตัวแปร — สรุปจากกรอบแนวคิดของรายงานฉบับสมบูรณ์ (บทที่ 4
    # หัวข้อ 4.1: "ตัวแปรที่เป็นมาตรวัดผลกระทบของ ววน. แบ่งเป็น 3 กลุ่ม ได้แก่
    # กลุ่มที่ 1 ปัจจัยนำเข้าการพัฒนาทุนมนุษย์และการลงทุนเชิงนวัตกรรม กลุ่มที่ 2
    # ตัวชี้วัดการสร้างสรรค์และคุ้มครองทรัพย์สินทางปัญญา และกลุ่มที่ 3 ปัจจัยควบคุม
    # ทางเศรษฐกิจต่อการเติบโตของผลิตภาพ") ไม่ใช่คำอธิบายทั่วไปที่แต่งขึ้นเองอีกต่อไป
    _group_desc = {
        "ปัจจัยนำเข้า (Input)": (
            "ปัจจัยนำเข้าด้านการพัฒนาทุนมนุษย์และการลงทุนเชิงนวัตกรรม เช่น การลงทุนโดยตรง"
            "จากต่างประเทศ การพัฒนาทุนมนุษย์ และงบวิจัยและพัฒนาของภาครัฐ-ภาคเอกชน"
        ),
        "ผลผลิต (Output)": (
            "ตัวชี้วัดผลผลิตด้านการสร้างสรรค์และคุ้มครองทรัพย์สินทางปัญญา เช่น สิ่งพิมพ์ทาง"
            "วิทยาศาสตร์และเทคนิค สิทธิบัตร และอนุสิทธิบัตร"
        ),
        "ปัจจัยแวดล้อมทางเศรษฐกิจ": (
            "ปัจจัยควบคุมเชิงโครงสร้างทางเศรษฐกิจที่มีผลต่อการเติบโตของผลิตภาพ เช่น ความซับซ้อน"
            "ทางเศรษฐกิจด้านการค้าและอัตราการเปิดกว้างทางการค้า"
        ),
        "พจน์ปรับตัวของสมการ": (
            "องค์ประกอบทางสถิติที่สะท้อนความเร็วในการปรับตัวเข้าสู่ดุลยภาพระยะยาวของสมการ "
            "ไม่ใช่ตัวชี้วัดด้าน ววน. โดยตรง"
        ),
    }
    _group_icon = {
        "ปัจจัยนำเข้า (Input)": "database",
        "ผลผลิต (Output)": "trend-up",
        "ปัจจัยแวดล้อมทางเศรษฐกิจ": "bars",
        "พจน์ปรับตัวของสมการ": "settings",
    }

    _codes_by_group = {
        g: [
            c for c in VARIABLE_ORDER
            if c not in ("const",) and VARIABLE_EXPLANATIONS.get(c, {}).get("group") == g
        ]
        for g in _group_order
    }
    _n_indep = sum(len(v) for g, v in _codes_by_group.items() if g != "พจน์ปรับตัวของสมการ")
    _n_groups = sum(1 for g in _group_order if g != "พจน์ปรับตัวของสมการ" and _codes_by_group[g])

    st.markdown(
        '<div class="var-intro">'
        '<div class="var-intro-eyebrow">About the model</div>'
        '<h3>ตัวแปรที่ใช้ในแบบจำลอง TFP คืออะไรบ้าง</h3>'
        '<p>แบบจำลองนี้วิเคราะห์ผลกระทบของปัจจัยด้านวิทยาศาสตร์ วิจัย และนวัตกรรม (ววน.) '
        'ต่อผลิตภาพการผลิตรวมของประเทศไทย (Total Factor Productivity: TFP) โดยแบ่งตัวแปรอิสระ '
        'ออกเป็น 3 กลุ่มตามบทบาท ได้แก่ กลุ่มปัจจัยนำเข้า กลุ่มผลผลิต และกลุ่มปัจจัยแวดล้อมทางเศรษฐกิจ '
        'ตามรายละเอียดด้านล่างนี้ (หน้านี้ไม่แสดงตัวเลขข้อมูลดิบรายปี เนื่องจากถือเป็นข้อมูลที่มีความอ่อนไหว '
        'ต้องการดูค่าสัมประสิทธิ์และผลการประมาณการปัจจุบันของแบบจำลอง ดูได้ที่หน้า "ผลการวิเคราะห์")</p>'
        f'<div class="var-stats">'
        f'<div class="var-stat"><b>{_n_indep}</b><span>ตัวแปรอิสระ</span></div>'
        f'<div class="var-stat"><b>{_n_groups}</b><span>กลุ่มปัจจัย</span></div>'
        f'<div class="var-stat"><b>1</b><span>พจน์ปรับตัว (ECM)</span></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ----- (ไอเดียที่ 2) ปุ่ม jump-to ไปหาแต่ละกลุ่ม -----
    _group_slug = {
        "ปัจจัยนำเข้า (Input)": "group-input",
        "ผลผลิต (Output)": "group-output",
        "ปัจจัยแวดล้อมทางเศรษฐกิจ": "group-env",
        "พจน์ปรับตัวของสมการ": "group-ecm",
    }
    st.markdown(
        '<div class="var-jumpnav">' + "".join(
            f'<a class="var-jump-pill" href="#{_group_slug[g]}">{icon(_group_icon.get(g, "bars"), 13, 2)} {g}</a>'
            for g in _group_order if _codes_by_group[g]
        ) + '</div>',
        unsafe_allow_html=True,
    )

    # ----- กล่องค้นหาตัวแปร (พิมพ์ชื่อหรือรหัสตัวแปร กรองรายการด้านล่างทันที) -----
    _var_search = st.text_input(
        "ค้นหาตัวแปร", placeholder="พิมพ์ชื่อหรือรหัสตัวแปร เช่น \"FDI\" หรือ \"การลงทุน\"",
        key="var_search_box", label_visibility="collapsed",
    ).strip().lower()
    _any_group_shown = False

    for _group in _group_order:
        _codes_in_group = _codes_by_group[_group]
        if _var_search:
            _codes_in_group = [
                c for c in _codes_in_group
                if _var_search in c.lower() or _var_search in VARIABLE_LABELS.get(c, "").lower()
            ]
        if not _codes_in_group:
            continue
        _any_group_shown = True

        # (ไอเดียที่ 3) นับจำนวนตัวแปรที่หนุนเสริม (+) / ฉุดรั้ง (−) ในกลุ่มนี้ เพื่อ
        # ทำแถบสัดส่วนสีในหัวกลุ่ม — ใช้ direction_map (จากโมเดลจริงถ้ามี ไม่งั้น
        # ประมาณจากคำบรรยาย) เฉพาะกลุ่มปัจจัยนำเข้า/ผลผลิต/แวดล้อม ไม่รวม ECM
        # (ECM เป็นพจน์ปรับตัวทางสถิติ ไม่ใช่ตัวแปรที่มีทิศทางหนุน/ฉุด TFP ตรงๆ)
        _n_pos = _n_neg = 0
        if _group != "พจน์ปรับตัวของสมการ":
            for code in _codes_in_group:
                d = _direction_map.get(code) or _infer_direction_from_text(VARIABLE_EXPLANATIONS[code]["effect"])
                if d == "pos":
                    _n_pos += 1
                elif d == "neg":
                    _n_neg += 1

        # (ไอเดียที่ 4) หาตัวแปรที่มีสัดส่วนอิทธิพลสูงสุดในกลุ่มนี้ (มีข้อมูลเฉพาะ
        # ตอนดึงข้อมูล+รันโมเดลสำเร็จแล้ว และตัวแปรนั้นอยู่ในสมการระยะยาว)
        _top_code_in_group = None
        if _influence_pct_map:
            _group_pcts = {c: _influence_pct_map[c] for c in _codes_in_group if c in _influence_pct_map}
            if _group_pcts:
                _top_code_in_group = max(_group_pcts, key=_group_pcts.get)

        _rows_html = []
        for code in _codes_in_group:
            exp = VARIABLE_EXPLANATIONS[code]
            d = _direction_map.get(code) or _infer_direction_from_text(exp["effect"])
            _badge_html = (
                f'<span class="var-top-badge">{icon("sparkle", 10, 2)} มีอิทธิพลสูงสุดในกลุ่มนี้</span>'
                if code == _top_code_in_group else ""
            )
            _rows_html.append(
                f'<div class="var-item" style="--dir-color:{_dir_color[d]};">'
                f'<div class="var-item-top">'
                f'<span class="var-item-name">{VARIABLE_LABELS.get(code, code)}</span>'
                f'<span class="var-item-code">{code}</span>{_badge_html}'
                f'</div>'
                f'<div class="var-item-meta">ที่มา: {exp["source"]}<span class="sep">·</span>{exp["role"]}</div>'
                f'<p class="var-item-row"><b>คือ:</b> {exp["meaning"]}</p>'
                f'<p class="var-item-row"><b>ผลต่อ TFP ตามผลการศึกษา:</b> {exp["effect"]}</p>'
                f'</div>'
            )

        # (ไอเดียที่ 3 ต่อ) แถบสัดส่วน +/- ในหัวกลุ่ม — แสดงเฉพาะเมื่อจำแนกทิศทางได้
        # อย่างน้อย 1 ตัว จะได้ไม่โชว์แถบว่างๆ กรณีกลุ่ม ECM หรือจำแนกไม่ได้เลย
        _split_html = ""
        if _n_pos + _n_neg > 0:
            _pos_pct = _n_pos / (_n_pos + _n_neg) * 100
            _split_html = (
                f'<div class="var-group-split">'
                f'<div class="var-split-bar"><div class="pos" style="width:{_pos_pct:.0f}%;"></div>'
                f'<div class="neg" style="width:{100 - _pos_pct:.0f}%;"></div></div>'
                f'<span class="var-split-label">{_n_pos} หนุน · {_n_neg} ฉุด</span></div>'
            )

        st.markdown(
            f'<div class="var-group" id="{_group_slug[_group]}">'
            f'<div class="var-group-head">'
            f'<div class="var-group-head-icon-bg">{icon(_group_icon.get(_group, "bars"), 64, 1.6)}</div>'
            f'<div class="var-group-icon">{icon(_group_icon.get(_group, "bars"), 20, 2)}</div>'
            f'<div class="var-group-title-wrap"><h3>{_group}</h3><p>{_group_desc[_group]}</p></div>'
            f'{_split_html}'
            f'<div class="var-group-count">{len(_codes_in_group)} ตัวแปร</div>'
            f'</div>'
            f'<div class="var-list">{"".join(_rows_html)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if _var_search and not _any_group_shown:
        st.info(f'ไม่พบตัวแปรที่ตรงกับ "{_var_search}" — ลองพิมพ์คำอื่น หรือลบข้อความในช่องค้นหาเพื่อดูทั้งหมด')

    # ----- แหล่งอ้างอิงข้อมูลตัวแปร — วางไว้มุมขวาล่างของหน้า -----
    st.markdown(
        '<div style="text-align:right;margin-top:8px;padding:10px 4px;'
        'font-size:0.82rem;color:var(--brand-navy-soft);line-height:1.5;">'
        'แหล่งข้อมูล: นิยาม แหล่งที่มา และผลการศึกษาของตัวแปรทั้งหมดในหน้านี้ อ้างอิงจากรายงาน '
        '<i>"โครงการจัดทำแบบจำลองทางเศรษฐมิติสำหรับติดตามและประเมินผลนโยบายสำคัญ '
        'นำร่องอุตสาหกรรมเป้าหมายในแผนด้านวิทยาศาสตร์ วิจัย และนวัตกรรมของประเทศ พ.ศ. 2566–2570"'
        '</i><br>จัดทำภายใต้แผนด้านวิทยาศาสตร์ วิจัย และนวัตกรรมของประเทศ '
        'โดยสำนักงานสภานโยบายการอุดมศึกษา วิทยาศาสตร์ วิจัย และนวัตกรรมแห่งชาติ (สอวช.)'
        '</div>',
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------------------------
# หน้า "คู่มือการใช้งาน" — ขั้นตอนการใช้งานระบบแบบสรุป ไม่ขึ้นกับข้อมูลที่ดึงมา
# ------------------------------------------------------------------------------
elif st.session_state.page == "manual":
    st.markdown(
        f'<div class="nxpo-topbar"><div class="nxpo-topbar-left">'
        f'<div class="nxpo-topbar-logo">{icon("book", 22, 2)}</div>'
        f'<div class="nxpo-topbar-title"><h2>คู่มือการใช้งาน</h2>'
        f'<span class="eyebrow">User Guide</span></div></div></div>',
        unsafe_allow_html=True,
    )
    manual_steps = [
        ("database", "ดึงข้อมูลอัตโนมัติ", "กดปุ่ม \"คลิกดึงข้อมูลอัตโนมัติ\" ที่แถบเมนูด้านซ้าย เพื่อโหลดข้อมูลล่าสุดและรันโมเดลอัตโนมัติ"),
        ("calendar", "กำหนดช่วงเวลาพยากรณ์", "ในหน้า \"Dashboard พยากรณ์ TFP\" เลือกจำนวนปีที่ต้องการพยากรณ์ล่วงหน้าจากรายการ (3/5/10/15 ปี) ระบบจะเลือกโมเดล ARIMA ที่เหมาะสมให้อัตโนมัติ"),
        ("trend-up", "ดูผลพยากรณ์และตัวแปรในสมการ", "ดูกราฟแนวโน้ม TFP ตัวแปรในสมการระยะสั้น/ระยะยาว และผลตรวจสอบข้อสมมติฐานได้จากเมนู \"Dashboard พยากรณ์ TFP\" และ \"ทำความรู้จักตัวแปร\""),
        ("sparkle", "สร้างแดชบอร์ดสำหรับนำเสนอ", "หลังตั้งค่าช่วงปีพยากรณ์/สมมติฐานตัวแปรแล้ว เลื่อนลงสุดหน้าแล้วกดปุ่ม \"สร้างแดชบอร์ดสำหรับนำเสนอ (สรุปหน้าเดียว)\" เพื่อดูสรุปทุกอย่างในจอเดียว เหมาะสำหรับนำเสนอ"),
        ("lock", "เข้าสู่ระบบสำหรับคณะวิจัย", "คณะวิจัยเข้าสู่ระบบด้วยบัญชีที่ได้รับสิทธิ์ เพื่อปรับแต่งตัวแปรในสมการและสร้างรายงานสรุปสำหรับนำเสนอด้วย AI"),
        ("download", "ดาวน์โหลดรายงาน", "ดาวน์โหลดตัวเลขพยากรณ์ ตารางผลการวิเคราะห์ หรือรายงานสรุปเป็นไฟล์ CSV/Word/PowerPoint ได้จากปุ่มดาวน์โหลดในแต่ละหมวด"),
    ]
    for i, (ic, title, desc) in enumerate(manual_steps, start=1):
        st.markdown(
            f'<div class="section-card"><div class="section-title">'
            f'<div class="section-num">{i}</div>'
            f'<div class="section-title-text"><h3>{title}</h3>'
            f'<p style="margin:3px 0 0 0;color:var(--brand-navy-soft);font-size:0.9rem;line-height:1.65;">{desc}</p>'
            f'</div></div></div>',
            unsafe_allow_html=True,
        )

    # ----- ศัพท์ที่ควรรู้ (Glossary) — อธิบายคำศัพท์เชิงเทคนิคที่ปรากฏในระบบด้วย
    # ภาษาง่ายๆ สำหรับคนทั่วไปที่ไม่ใช่นักเศรษฐมิติ ให้เข้ากับ mood ของหน้าแรกที่
    # อยากให้คนทั่วไปเข้าใจได้ว่าระบบใช้ทำอะไร -----
    st.markdown(
        f'<div class="section-card"><div class="section-title">'
        f'<div class="section-num">{icon("book", 20, 2)}</div>'
        f'<div class="section-title-text"><h3>ศัพท์ที่ควรรู้</h3>'
        f'<p style="margin:3px 0 0 0;color:var(--brand-navy-soft);font-size:0.9rem;">'
        f'คำศัพท์เชิงเทคนิคที่ปรากฏในระบบ อธิบายแบบเข้าใจง่าย</p></div></div>',
        unsafe_allow_html=True,
    )
    _glossary = [
        ("TFP (Total Factor Productivity)",
         "ผลิตภาพการผลิตรวม — วัดว่าเศรษฐกิจผลิตได้มากขึ้นแค่ไหนจากแรงงานและทุนจำนวนเท่าเดิม "
         "ส่วนที่เพิ่มขึ้นเกินกว่านั้นมักสะท้อนถึงเทคโนโลยีและนวัตกรรมที่ดีขึ้น"),
        ("ARIMA",
         "แบบจำลองพยากรณ์อนุกรมเวลา ที่ใช้ค่าในอดีตของตัวแปรเองมาพยากรณ์อนาคต "
         "เหมาะกับข้อมูลที่มีแนวโน้ม/รูปแบบต่อเนื่องจากอดีต เช่น TFP รายปี"),
        ("พจน์ปรับตัวของสมการ (ECM)",
         "ส่วนที่บอกว่า เมื่อค่าจริงเบี่ยงเบนไปจาก \"จุดสมดุลระยะยาว\" แล้ว จะปรับตัวกลับเข้าสู่จุดสมดุลนั้นเร็วแค่ไหน"),
        ("AIC (Akaike Information Criterion)",
         "ตัวเลขที่ใช้เทียบว่าโมเดลแบบไหน \"พอดี\" กับข้อมูลที่สุดโดยไม่ซับซ้อนเกินความจำเป็น ยิ่งค่าต่ำยิ่งดี"),
        ("p-value",
         "ความน่าจะเป็นที่ผลลัพธ์ที่เห็นเกิดจากความบังเอิญล้วนๆ โดยทั่วไปถ้าต่ำกว่า 0.05 "
         "จะถือว่าผลนั้น \"มีนัยสำคัญทางสถิติ\" คือไม่น่าจะเกิดจากความบังเอิญ"),
        ("R² / Adjusted R²",
         "สัดส่วนความผันแปรของ TFP ที่แบบจำลองอธิบายได้ ค่ายิ่งใกล้ 1 (หรือ 100%) ยิ่งอธิบายข้อมูลได้ดี"),
        ("ช่วงความเชื่อมั่น 95%",
         "ช่วงตัวเลขที่คาดว่าค่าจริงในอนาคตจะตกอยู่ในช่วงนี้ด้วยความมั่นใจ 95% "
         "ยิ่งพยากรณ์ไกลออกไปในอนาคต ช่วงนี้จะยิ่งกว้างขึ้น สะท้อนความไม่แน่นอนที่เพิ่มขึ้น"),
        ("สัมประสิทธิ์มาตรฐาน (Standardized coefficient)",
         "ค่าสัมประสิทธิ์ที่ปรับหน่วยของตัวแปรให้เทียบกันได้ ใช้บอกว่าตัวแปรไหน \"มีอิทธิพล\" "
         "ต่อ TFP มากกว่ากันในสมการเดียวกัน"),
    ]
    _glossary_html = "".join(
        f'<div class="var-item-row" style="margin-bottom:14px;">'
        f'<b style="display:block;color:var(--brand-navy);font-family:var(--font-elegant);'
        f'font-size:0.98rem;margin-bottom:3px;">{term}</b>{definition}</div>'
        for term, definition in _glossary
    )
    st.markdown(
        f'<div class="section-card" style="padding-top:6px;">{_glossary_html}</div>',
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------------------------
# หน้า "จัดการข้อมูลอัตโนมัติ" — เวอร์ชันขยายของปุ่มดึงข้อมูลที่แถบด้านซ้าย
# ------------------------------------------------------------------------------
elif st.session_state.page == "data_admin":
    st.markdown(
        f'<div class="nxpo-topbar"><div class="nxpo-topbar-left">'
        f'<div class="nxpo-topbar-logo">{icon("cloud", 22, 2)}</div>'
        f'<div class="nxpo-topbar-title"><h2>จัดการข้อมูลอัตโนมัติ</h2>'
        f'<span class="eyebrow">Data Management</span></div></div></div>',
        unsafe_allow_html=True,
    )
    # หน้านี้จำกัดให้เฉพาะคณะวิจัยที่ล็อกอินแล้วเท่านั้น เพราะเป็นการจัดการแหล่งข้อมูล
    # ต้นทางของระบบ (เปลี่ยนลิงก์ Google Sheet ได้) — ไม่ควรเปิดให้บุคคลภายนอกเข้าถึง
    if not st.session_state.research_authenticated:
        st.markdown(
            f'<div class="section-card" style="max-width:420px;margin:40px auto;'
            f'text-align:center;">'
            f'<div class="section-title" style="justify-content:center;align-items:center;">'
            f'<div class="section-num" style="position:relative;top:-3px;margin-top:0;">🔒</div>'
            f'<div class="section-title-text"><h3>สำหรับคณะวิจัยเท่านั้น</h3></div></div>'
            f'<p style="color:var(--brand-navy-soft);font-size:0.9rem;margin-top:-6px;">'
            f'กรุณาเข้าสู่ระบบด้วยบัญชีคณะวิจัยก่อน<br>จึงจะจัดการข้อมูลอัตโนมัติหน้านี้ได้</p></div>',
            unsafe_allow_html=True,
        )
        _data_admin_login_col = st.columns([1, 1.4, 1])[1]
        with _data_admin_login_col:
            if st.button("ไปที่หน้าเข้าสู่ระบบ →", use_container_width=True, key="data_admin_goto_login"):
                st.session_state.page = "home"
                st.rerun()
        st.stop()
    st.markdown(
        f'<div class="section-card"><div class="section-title">'
        f'<div class="section-num">{icon("cloud", 20, 2)}</div>'
        f'<div class="section-title-text"><h3>ดึงข้อมูลล่าสุดจากแหล่งข้อมูลภายนอก</h3>'
        f'<p style="margin:3px 0 0 0;color:var(--brand-navy-soft);font-size:0.9rem;">'
        f'อัปเดตข้อมูลแล้วรันโมเดล TFP ใหม่ทั้งหมดโดยอัตโนมัติ</p></div></div></div>',
        unsafe_allow_html=True,
    )
    # ----- ช่องกรอกลิงก์ Google Sheet เอง — ให้คณะวิจัยเปลี่ยนแหล่งข้อมูลได้เอง
    # โดยไม่ต้องแก้โค้ด (ถ้าเว้นว่างไว้ ระบบจะใช้ลิงก์เดิมที่ตั้งไว้ในโค้ดตามปกติ) -----
    st.markdown(
        f'<div class="section-card"><div class="section-title">'
        f'<div class="section-num">{icon("database", 20, 2)}</div>'
        f'<div class="section-title-text"><h3>ลิงก์ Google Sheet (สำหรับคณะวิจัย)</h3>'
        f'<p style="margin:3px 0 0 0;color:var(--brand-navy-soft);font-size:0.9rem;">'
        f'ระบุลิงก์ Google Sheet ของชุดข้อมูลที่ต้องการใช้แทนค่าเริ่มต้น '
        f'เว้นว่างไว้หากต้องการใช้แหล่งข้อมูลเดิม</p></div></div></div>',
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("custom_gsheet_url", "")
    st.session_state.custom_gsheet_url = st.text_input(
        "ลิงก์ Google Sheet",
        value=st.session_state.custom_gsheet_url,
        placeholder="https://docs.google.com/spreadsheets/d/...",
        key="custom_gsheet_url_input",
        label_visibility="collapsed",
    )
    st.caption(
        "หมายเหตุ: ต้องแชร์ Google Sheet เป็น \"ทุกคนที่มีลิงก์ - ดูได้\" (หรือแชร์ให้อีเมล "
        "service account ที่ตั้งค่าไว้) และต้องมีแท็บ \"Data\"/\"Researcher\" โครงสร้างเหมือน "
        "Sheet ต้นแบบทุกประการ ระบบจึงจะดึงข้อมูลจากลิงก์นี้ได้สำเร็จ"
    )
    st.write("")

    if st.session_state.get("gsheet_load_error"):
        st.markdown(
            status_banner("error", f"ดึงข้อมูลไม่สำเร็จ: {st.session_state.gsheet_load_error}"),
            unsafe_allow_html=True,
        )
    elif "gsheet_raw_df" in st.session_state:
        st.markdown(status_banner("success", f"ดึงข้อมูลล่าสุดเมื่อ {thai_timestamp()}"), unsafe_allow_html=True)
    else:
        st.markdown(status_banner("info", "ยังไม่เคยดึงข้อมูลในเซสชันนี้"), unsafe_allow_html=True)
    if st.button("คลิกดึงข้อมูลอัตโนมัติ", key="data_admin_fetch_btn"):
        st.session_state.pop("gsheet_load_error", None)
        try:
            with st.spinner("กำลังดึงข้อมูลอัตโนมัติ..."):
                st.session_state.gsheet_raw_df = _load_data_gsheet_with_optional_url(
                    st.session_state.get("custom_gsheet_url")
                )
            st.session_state.gsheet_loaded_at = now_th()
            _log_fetch_event()
            st.rerun()
        except Exception as e:
            st.session_state.gsheet_load_error = str(e)
            st.session_state.pop("gsheet_raw_df", None)

    # ----- ประวัติการอัปเดตข้อมูล — เพื่อความโปร่งใสว่าดึงข้อมูลล่าสุดเมื่อไหร่บ้าง
    # (เก็บเป็นไฟล์ log อย่างง่ายในเครื่องที่รันแอป ไม่ใช่ระบบฐานข้อมูลกลาง) -----
    st.markdown(
        f'<div class="section-card"><div class="section-title">'
        f'<div class="section-num">{icon("clock", 20, 2)}</div>'
        f'<div class="section-title-text"><h3>ประวัติการอัปเดตข้อมูล</h3>'
        f'<p style="margin:3px 0 0 0;color:var(--brand-navy-soft);font-size:0.9rem;">'
        f'บันทึกอัตโนมัติทุกครั้งที่ดึงข้อมูลสำเร็จ (10 รายการล่าสุด)</p></div></div>',
        unsafe_allow_html=True,
    )
    _log_rows = _read_fetch_log(limit=10)
    if not _log_rows:
        st.info("ยังไม่มีประวัติการดึงข้อมูล")
    else:
        _log_rows_html = "".join(
            f'<tr><td>{r.get("timestamp", "-")}</td><td>{r.get("user", "-")}</td></tr>'
            for r in _log_rows
        )
        st.markdown(
            f'<div class="section-card" style="padding-top:10px;">'
            f'<div style="overflow-x:auto;"><table class="tfp-table" style="font-size:0.85rem;">'
            f'<thead><tr><th>เวลาที่ดึงข้อมูล</th><th>ดึงโดย</th></tr></thead>'
            f'<tbody>{_log_rows_html}</tbody></table></div></div>',
            unsafe_allow_html=True,
        )

# ------------------------------------------------------------------------------
# หน้า "ตั้งค่าระบบ" — ข้อมูลเวอร์ชันแอปและหมายเหตุทั่วไป (placeholder — ยังไม่มี
# การตั้งค่าที่ผู้ใช้แก้ไขได้จริงในเวอร์ชันนี้)
# ------------------------------------------------------------------------------
elif st.session_state.page == "settings":
    st.markdown(
        f'<div class="nxpo-topbar"><div class="nxpo-topbar-left">'
        f'<div class="nxpo-topbar-logo">{icon("settings", 22, 2)}</div>'
        f'<div class="nxpo-topbar-title"><h2>ตั้งค่าระบบ</h2>'
        f'<span class="eyebrow">System Settings</span></div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-card"><div class="section-title">'
        f'<div class="section-num">{icon("info", 20, 2)}</div>'
        '<div class="section-title-text"><h3>เกี่ยวกับระบบ</h3>'
        '<p style="margin:3px 0 0 0;color:var(--brand-navy-soft);font-size:0.9rem;line-height:1.7;">'
        f'ระบบแบบจำลองเศรษฐมิติมหภาค (TFP) — NXPO Data Center<br>เวอร์ชัน {APP_VERSION}'
        '</p></div></div></div>',
        unsafe_allow_html=True,
    )
    st.info("การตั้งค่าเพิ่มเติม (เช่น การสลับธีมสี การแจ้งเตือน) จะเปิดให้ใช้งานในเวอร์ชันถัดไป")

# ------------------------------------------------------------------------------
# ท้ายหน้าเว็บ — เดิมมี footer กลางหน้าแสดงโลโก้ สอวช./สวค./มหาวิทยาลัย/ภาควิชา +
# ข้อมูลผู้จัดทำอยู่ตรงนี้ ปัจจุบันถูกลบออกแล้ว เพราะย้ายโลโก้มหาวิทยาลัย/ภาควิชา
# และข้อมูลผู้จัดทำทั้งหมดไปแสดงเล็ก ๆ ท้ายแถบเมนูด้านซ้ายแทน (ดูตัวแปร
# _corner_badge_html ที่ประกาศไว้ต้นไฟล์แถวเดียวกับที่กำหนด logo3_html/logo4_html
# และเรียกใช้จริงใน `with st.sidebar:` ด้านบน)
# ------------------------------------------------------------------------------
