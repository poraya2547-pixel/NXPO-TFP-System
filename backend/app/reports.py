"""ไฟล์รายงาน Word/PowerPoint — ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit 7bf84e4)
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


# คัดลอกจาก TFP_App1.3.0.py:41-41 (7bf84e4)
TH_TZ = timezone(timedelta(hours=7))


# คัดลอกจาก TFP_App1.3.0.py:44-47 (7bf84e4)
def now_th() -> datetime:
    """คืนค่าเวลาปัจจุบันตามเวลาประเทศไทย (UTC+7) แบบ naive datetime
    (ตัด tzinfo ออกเพื่อให้ยังใช้ .strftime() ต่อได้เหมือนโค้ดเดิมทุกจุด)"""
    return datetime.now(TH_TZ).replace(tzinfo=None)


# คัดลอกจาก TFP_App1.3.0.py:1679-1679 (7bf84e4)
GEMINI_MODEL = "gemini-2.5-flash"


# คัดลอกจาก TFP_App1.3.0.py:1740-1741 (7bf84e4)
THAI_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


# คัดลอกจาก TFP_App1.3.0.py:1744-1747 (7bf84e4)
def thai_timestamp() -> str:
    now = now_th()
    return (f"{now.day} {THAI_MONTHS[now.month]} {now.year + 543} "
            f"เวลา {now.strftime('%H:%M')} น.")


# คัดลอกจาก TFP_App1.3.0.py:1785-1794 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:1886-1886 (7bf84e4)
_THAI_FONTS_REGISTERED = False


# ย้ายจาก TFP_App1.3.0.py:1889-1895 (7bf84e4)
def _register_thai_fonts():
    global _THAI_FONTS_REGISTERED
    if _THAI_FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("Sarabun", os.path.join(FONT_DIR, "Sarabun-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Sarabun-Bold", os.path.join(FONT_DIR, "Sarabun-Bold.ttf")))
    _THAI_FONTS_REGISTERED = True


# ย้ายจาก TFP_App1.3.0.py:1898-1907 (7bf84e4)
def _xml_escape(text: str) -> str:
    """แปลงอักขระ &, <, > ในข้อความดิบให้เป็น XML entity ที่ปลอดภัยก่อนแทรกเข้า
    ReportLab Paragraph (ซึ่ง parse เนื้อหาแบบ XML/HTML ย่อย) — ต้องเรียกก่อนแทรก
    markup ของเราเอง (<b>, &nbsp; ฯลฯ) เสมอ

    นี่คือสาเหตุของบั๊ก "R&D" กลายเป็น "R&D;" ที่เจอ: ตัว "&" ดิบที่ไม่ได้ escape
    ทำให้ ReportLab พยายาม parse มันเป็นจุดเริ่มต้นของ XML entity แล้วไล่กิน
    ตัวอักษรถัดไปเรื่อยๆ จนกว่าจะเจอ ';' ตัวแรกที่พบ (ซึ่งอาจมาจาก '&nbsp;' ที่เรา
    แทรกไว้ทีหลังในข้อความเดียวกัน) ทำให้ข้อความระหว่างทางหายไปและเหลือ ';' ค้าง"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ย้ายจาก TFP_App1.3.0.py:1910-1929 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2272-2288 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2291-2299 (7bf84e4)
def _docx_shade_cell(cell, hex_color: str):
    """ใส่สีพื้นหลังให้เซลล์ตาราง python-docx (ไม่มี API สำเร็จรูปให้ใช้ ต้องแทรก
    element w:shd เข้าไปใน tcPr เอง)"""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = docx_OxmlElement("w:shd")
    shd.set(docx_qn("w:val"), "clear")
    shd.set(docx_qn("w:color"), "auto")
    shd.set(docx_qn("w:fill"), hex_color)
    tcPr.append(shd)


# ย้ายจาก TFP_App1.3.0.py:2302-2312 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2315-2327 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2330-2367 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2370-2370 (7bf84e4)
_MPL_THAI_FONT_LOADED = False


# ย้ายจาก TFP_App1.3.0.py:2373-2386 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2389-2435 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2438-2620 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2627-2627 (7bf84e4)
NAVY = RGBColor(0x0F, 0x2B, 0x46)


# ย้ายจาก TFP_App1.3.0.py:2628-2628 (7bf84e4)
SLATE = RGBColor(0x4A, 0x55, 0x61)


# ย้ายจาก TFP_App1.3.0.py:2629-2629 (7bf84e4)
LIGHT_GREY = RGBColor(0x9A, 0xA5, 0xB1)


# ย้ายจาก TFP_App1.3.0.py:2630-2630 (7bf84e4)
ROW_TINT = RGBColor(0xEE, 0xF2, 0xF6)


# ย้ายจาก TFP_App1.3.0.py:2633-2682 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2685-2689 (7bf84e4)
def _estimate_bullet_lines(bullet_text: str, chars_per_line: int = 68) -> float:
    """ประมาณจำนวนบรรทัดที่ bullet หนึ่งข้อความจะตัดคำ (word-wrap) ภายในกล่องข้อความ
    กว้าง ~11.3 นิ้ว ที่ขนาดฟอนต์ 15-16pt — ใช้ประมาณความสูงที่ต้องใช้จริง เพื่อกันเนื้อหา
    ล้นสไลด์ (คำนวณคร่าว ๆ พอเพียงสำหรับแบ่งหน้า ไม่ต้องแม่นยำระดับพิกเซล)"""
    return max(1.0, math.ceil(len(bullet_text) / chars_per_line))


# ย้ายจาก TFP_App1.3.0.py:2692-2708 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2711-2723 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2726-2739 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2742-2742 (7bf84e4)
ORANGE = RGBColor(0xF2, 0x81, 0x1D)


# ย้ายจาก TFP_App1.3.0.py:2745-2752 (7bf84e4)
def _add_title_accent(slide, prs, x=Inches(0.8), y=Inches(1.22), width=Inches(0.55)):
    """ขีดเส้นสั้น ๆ สีส้มใต้หัวข้อสไลด์ — เพิ่มจุดเน้นเล็ก ๆ ให้สไลด์ดูมีดีไซน์
    มากกว่าปล่อยว่างระหว่างหัวข้อกับเนื้อหา (มินิมอล ไม่ใช่เส้นเต็มความกว้างสไลด์)"""
    bar = slide.shapes.add_shape(1, x, y, width, Pt(3.5))  # 1 = MSO_SHAPE.RECTANGLE
    bar.fill.solid()
    bar.fill.fore_color.rgb = ORANGE
    bar.line.fill.background()
    bar.shadow.inherit = False


# ย้ายจาก TFP_App1.3.0.py:2755-2769 (7bf84e4)
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


# ย้ายจาก TFP_App1.3.0.py:2772-2773 (7bf84e4)
def _blank_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


# ย้ายจาก TFP_App1.3.0.py:2776-3066 (7bf84e4)
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

