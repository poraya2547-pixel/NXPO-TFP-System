"""สร้าง backend/app/page_script.py จากโค้ดหน้าเว็บเดิม TFP_App1.3.0.py ที่ root ของ workspace (4c8aa71; ก่อน 20 ต.ค. คือ acc64ee, ก่อน 10 ต.ค. คือ e6aee03)
แบบคัดลอกทั้งไฟล์

ต่างจากต้นฉบับเฉพาะที่ประกาศในไฟล์นี้ (ตรวจด้วย backend/tests/test_moved_page.py):
1. ลบ top-level definitions ที่ย้ายไปไว้ที่อื่น (MOVED) แล้ว import ชื่อเดิมกลับมาจากที่ใหม่ (IMPORT_LINES)
2. แทนข้อความตรงตัวตาม TEXT_CHANGES (แต่ละข้อความต้องพบครั้งเดียว)
สคริปต์ที่ได้ถูก exec ต่อคำขอโดย page_runner.py พร้อม `st` ตัวแทน (ui.PageRun) — ห้ามแก้ไฟล์ที่สร้างด้วยมือ

    /opt/anaconda3/envs/idntwww/bin/python -B tools/refactor/extract_page.py
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "TFP_App1.3.0.py"
OUT = REPO / "backend" / "app" / "page_script.py"
sys.path.insert(0, str(REPO / "tools" / "baseline"))
sys.path.insert(0, str(REPO / "tools" / "refactor"))
import safe_io  # noqa: E402
from extract_core import CHARTS, CORE  # noqa: E402

# ชื่อที่หน้าเว็บอ่านผลจาก worker แทนการคำนวณเอง (backend/app/page_api.py)
# _build_adf_detail_table (acc64ee): worker คำนวณตาราง ADF ไว้ใน ECM bundle หน้าไม่ fit เอง
LOOKUPS = ["_run_backtest", "_run_rolling_backtest", "_unrounded_coefficient_table", "_build_adf_detail_table"]
# ตัวสร้างกราฟที่เดิมวางลงหน้าเอง — page_api ห่อให้วางลงหน้าแบบเดิม
CHART_WRAPPERS = ["_nice_line_chart", "_nice_line_chart_with_forecast", "_mape_threshold_chart"]
GEMINI = ["_GEMINI_RETRYABLE_STATUS_CODES", "_GEMINI_MAX_ATTEMPTS", "_GEMINI_BASE_DELAY", "SYSTEM_PROMPT",
          "_eg_text", "generate_summary_gemini"]
REPORTS = ["_THAI_FONTS_REGISTERED", "_register_thai_fonts", "_xml_escape", "_md_line_to_flowable",
           "_docx_set_thai_font", "_docx_shade_cell", "_docx_add_bottom_border", "_docx_add_runs_with_bold",
           "_docx_add_md_line", "_MPL_THAI_FONT_LOADED", "_register_thai_font_matplotlib", "_build_tfpi_chart_png",
           "build_word_report", "NAVY", "SLATE", "LIGHT_GREY", "ROW_TINT", "_parse_summary_sections",
           "_estimate_bullet_lines", "_chunk_bullets", "_add_logos_top_right", "_add_footer", "ORANGE",
           "_add_title_accent", "_add_page_number", "_blank_slide", "build_pptx_report"]
FETCH = ["_load_data_gsheet_with_optional_url"]
# 4c8aa71: ผล backtest ที่คำนวณแล้วเก็บในไฟล์ backtest_cache.pkl — ระบบใหม่ไม่ใช้ไฟล์ (ผู้ใช้เลือก 20 ต.ค.)
# ผลของ worker เก็บใน DB ต่อชุดข้อมูลอยู่แล้ว: "มีผลในไฟล์" = มีผล series ใน DB, อ่านผล = lookup ของ worker
BT_CACHE_REPLACED = ["_backtest_with_file_cache", "_bt_cache_has"]  # page_api ทำงานแทน
BT_CACHE_DROPPED = ["_BT_CACHE_FILE", "_bt_cache_key", "_bt_cache_load", "_bt_cache_save", "_bt_pack",
                    "_bt_unpack"]  # อ่าน/เขียนไฟล์ .pkl เท่านั้น ไม่มีที่ใช้หลังแทนสองชื่อบน
# ชื่อ → ปลายทาง (คัดลอก AST เดิมไปไว้ในโมดูลนั้น; หน้าเว็บ import ชื่อเดิมจาก core/charts หรือ page_api ที่ทำงานแทน
# สำหรับ job: jobs = ดึงชีตใน worker; reports/summary = รายงานและ Gemini (Step 7))
MOVED = {**{n: "core" for n in CORE}, **{n: "charts" for n in CHARTS}, **{n: "summary" for n in GEMINI},
         **{n: "reports" for n in REPORTS}, **{n: "jobs" for n in FETCH},
         **{n: "page_api" for n in BT_CACHE_REPLACED}, **{n: "dropped" for n in BT_CACHE_DROPPED}}

IMPORT_LINES = (
    "from app.charts import FONT_FAMILY\n"
    "from app.modeling.core import (\n"
    + "".join(f"    {n},\n" for n in CORE if n not in LOOKUPS) +
    ")\n"
    "from app.page_api import (\n"
    + "".join(f"    {n},\n" for n in LOOKUPS + CHART_WRAPPERS + FETCH + BT_CACHE_REPLACED
              + ["generate_summary_gemini", "build_word_report", "build_pptx_report",
                 "_fetch_log_append", "_fetch_log_rows", "_cached_file_b64", "_page_clock"]) +
    ")\n"
)

TEXT_CHANGES = [
    # st มาจาก page_runner (ui.PageRun) ไม่ใช่ Streamlit
    ("import streamlit as st\n", ""),
    # ฟังก์ชันของ TFP.py ที่ fit โมเดลอ่านผลจาก worker (ค่าคงที่และฟังก์ชันที่ไม่ fit ใช้ของจริงผ่าน page_api)
    ("from TFP import (\n", "from app.page_api import (\n"),
    # ดึงชีตเป็น job ของ worker (page_api._load_data_gsheet_with_optional_url)
    ("from data_loader import load_data_gsheet\n", ""),
    ("from typing import Optional\n", "from typing import Optional\n" + IMPORT_LINES),
    # หลังได้ข้อมูลจากงานดึงชีต เวลาของคำขอนั้นนับจากเวลาที่ worker อ่านชีตสำเร็จ (page_api._page_clock, แผน §9A)
    ("    return datetime.now(TH_TZ).replace(tzinfo=None)\n",
     "    return _page_clock(datetime.now(TH_TZ)).replace(tzinfo=None)\n"),
    # ไฟล์ภาพ/ฟอนต์ใน image ไม่เปลี่ยน อ่านครั้งเดียวต่อ process
    ('def _font_b64(filename: str) -> str:\n'
     '    with open(os.path.join(FONT_DIR, filename), "rb") as f:\n'
     '        return base64.b64encode(f.read()).decode()\n',
     'def _font_b64(filename: str) -> str:\n'
     '    return _cached_file_b64(os.path.join(FONT_DIR, filename))\n'),
    ('def img_to_base64(path):\n'
     '    with open(path, "rb") as f:\n'
     '        return base64.b64encode(f.read()).decode()\n',
     'def img_to_base64(path):\n'
     '    return _cached_file_b64(path)\n'),
    # บันทึกการดึงข้อมูล: จากไฟล์ fetch_log.csv ข้างแอป → ตาราง fetch_log ใน Postgres
    ('        file_exists = os.path.exists(FETCH_LOG_PATH)\n'
     '        with open(FETCH_LOG_PATH, "a", encoding="utf-8-sig", newline="") as f:\n'
     '            writer = csv.DictWriter(f, fieldnames=["timestamp", "user"])\n'
     '            if not file_exists:\n'
     '                writer.writeheader()\n'
     '            writer.writerow(row)\n',
     '        _fetch_log_append(row)\n'),
    ('    if not os.path.exists(FETCH_LOG_PATH):\n'
     '        return []\n'
     '    try:\n'
     '        with open(FETCH_LOG_PATH, encoding="utf-8-sig", newline="") as f:\n'
     '            rows = list(csv.DictReader(f))\n'
     '        return list(reversed(rows))[:limit]\n',
     '    try:\n'
     '        rows = _fetch_log_rows()\n'
     '        return list(reversed(rows))[:limit]\n'),
]

HEAD = '''"""โค้ดหน้าเว็บที่ย้ายจาก TFP_App1.3.0.py (repo เพื่อน commit 4c8aa71) — สร้างด้วย tools/refactor/extract_page.py ห้ามแก้ด้วยมือ

ต่างจากต้นฉบับเฉพาะ: ลบนิยามที่ย้ายไปไว้ที่อื่นแล้ว import กลับมา และแทนข้อความตาม TEXT_CHANGES ของตัวสร้าง
ไฟล์นี้ไม่ได้ถูก import เป็นโมดูล — page_runner.py exec ต่อคำขอพร้อม `st` ตัวแทน (backend/app/ui.py)
"""
'''


def top_level_nodes(src: str):
    nodes = {}
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef):
            name = n.name
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            name = n.targets[0].id
        else:
            continue
        if name in MOVED:
            if name in nodes:
                raise RuntimeError(f"{name} ถูกนิยามซ้ำ")
            nodes[name] = n
    missing = set(MOVED) - set(nodes)
    if missing:
        raise RuntimeError(f"ไม่พบ {sorted(missing)}")
    return nodes


def build(src: str) -> str:
    lines = src.splitlines(keepends=True)
    drop = set()
    for n in top_level_nodes(src).values():
        first = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        drop.update(range(first, n.end_lineno + 1))
    text = "".join(line for i, line in enumerate(lines, start=1) if i not in drop)
    for old, new in TEXT_CHANGES:
        if text.count(old) != 1:
            raise RuntimeError(f"ข้อความที่จะแทนพบ {text.count(old)} ครั้ง: {old[:60]!r}")
        text = text.replace(old, new)
    return HEAD + text


def main():
    src = APP.read_text(encoding="utf-8")
    out = build(src)
    compile(out, str(OUT), "exec")
    safe_io.ensure_absent([OUT])
    safe_io.write_new(OUT, out)
    print("เขียนแล้ว", OUT.relative_to(REPO), f"({len(out.splitlines())} บรรทัด)")


if __name__ == "__main__":
    main()
