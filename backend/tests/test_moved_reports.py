"""Step 7: summary.py (Gemini) และ reports.py (Word/PowerPoint) ต้องเป็นโค้ดเดิม — เทียบ AST กับ TFP_App1.3.0.py ที่ root (7bf84e4)

ต่างได้เฉพาะที่ประกาศ:
- summary.py: gemini_client = None และ st = None (หน้าเดิมสร้าง client ตอนเปิดแอปและใช้ streamlit — worker ตั้งให้ต่อ job)
- reports.py: APP_DIR/FONT_DIR ชี้โฟลเดอร์ภาพ/ฟอนต์ของระบบใหม่ (backend/app/assets — สำเนาทุก byte ตรวจใน test_moved_page)
- import: ต้องเป็นชื่อ (และชื่อแฝง) ที่แอปเดิม import จากโมดูลเดียวกัน; ชื่อจาก TFP ใช้ .modeling.tfp; _merge_coefficient_tables
  ใช้จาก .modeling.core (โค้ดเดิมที่ย้ายใน Step 2); pathlib ใช้หา APP_DIR
ไม่เชื่อตัวสร้างไฟล์ (tools/refactor/extract_reports.py) ใช้จากมันเพียงรายชื่อ
"""
import ast
import sys

import parity
from test_moved_source import APP, APP_TREE, dump, is_docstring, named, parse, rest

REPO = parity.REPO
NEW = REPO / "backend" / "app"
sys.path.insert(0, str(REPO / "tools" / "refactor"))
from extract_page import GEMINI, REPORTS  # noqa: E402
from extract_reports import REPORTS_COPIES, SUMMARY_COPIES  # noqa: E402

TFP_NAMES = {a.name for n in APP_TREE.body if isinstance(n, ast.ImportFrom) and n.module == "TFP" for a in n.names}


def app_import_aliases():
    out = {}
    for n in APP_TREE.body:
        if isinstance(n, ast.ImportFrom):
            out.setdefault(("from", n.module, n.level), set()).update((a.name, a.asname) for a in n.names)
        elif isinstance(n, ast.Import):
            out.setdefault(("import", None, 0), set()).update((a.name, a.asname) for a in n.names)
    return out


def assert_imports_subset_of_app(tree, allowed_extra):
    app = app_import_aliases()
    for n in rest(tree):
        if not isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        if ast.unparse(n) in allowed_extra:
            continue
        key = ("from", n.module, n.level) if isinstance(n, ast.ImportFrom) else ("import", None, 0)
        names = {(a.name, a.asname) for a in n.names}
        assert names <= app.get(key, set()), f"import ที่ไม่มีในไฟล์แอปเดิม: {ast.unparse(n)}"


def assert_same_code(path, moved, copied, declared):
    tree = parse(path)
    new = named(tree)
    expected = sorted(moved + copied, key=lambda n: APP[n].lineno)
    assert [n for n in new if n not in declared] == expected, "ชื่อหรือลำดับไม่ตรงกับไฟล์แอปเดิม"
    for name in expected:
        assert dump(new[name]) == dump(APP[name]), f"{name} ไม่ตรงกับต้นฉบับ"
    for name, src in declared.items():
        assert ast.unparse(new[name]) == src, name
    return tree


def test_summary_is_original_code():
    tree = assert_same_code(NEW / "summary.py", GEMINI, SUMMARY_COPIES,
                            {"gemini_client": "gemini_client = None", "st": "st = None"})
    others = rest(tree)
    assert is_docstring(others[0]) and all(isinstance(n, (ast.Import, ast.ImportFrom)) for n in others[1:])
    imports = [ast.unparse(n) for n in others[1:]]
    tfp_import = "from .modeling.tfp import build_coefficient_tables, build_tfpi_yoy_summary, summary_adj_r2"
    assert tfp_import in imports and {"build_coefficient_tables", "build_tfpi_yoy_summary", "summary_adj_r2"} <= TFP_NAMES
    assert_imports_subset_of_app(tree, {tfp_import})


def test_reports_is_original_code():
    tree = assert_same_code(NEW / "reports.py", REPORTS, REPORTS_COPIES, {
        "APP_DIR": "APP_DIR = str(Path(__file__).resolve().parent / 'assets')",
        "FONT_DIR": "FONT_DIR = os.path.join(APP_DIR, 'fonts')"})
    # FONT_DIR ใช้สูตรเดียวกับแอปเดิม (TFP_App1.3.0.py:123)
    assert dump(named(tree)["FONT_DIR"]) == dump(APP["FONT_DIR"])
    others = rest(tree)
    assert is_docstring(others[0])
    # คำสั่งอื่นนอกจาก import: matplotlib.use("Agg") บรรทัดเดียวกับแอปเดิม (TFP_App1.3.0.py:32)
    exprs = [n for n in others[1:] if not isinstance(n, (ast.Import, ast.ImportFrom))]
    app_use = [n for n in APP_TREE.body if isinstance(n, ast.Expr) and ast.unparse(n) == "matplotlib.use('Agg')"]
    assert [dump(n) for n in exprs] == [dump(n) for n in app_use] and len(app_use) == 1
    extra = {"from pathlib import Path", "from .modeling.core import _merge_coefficient_tables",
             "from .modeling.tfp import DEP_VAR"}
    assert "DEP_VAR" in TFP_NAMES
    imports = {ast.unparse(n) for n in others if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert extra <= imports
    assert_imports_subset_of_app(tree, extra)


def test_moved_names_are_gone_from_the_page_and_copies_remain():
    page = named(parse(NEW / "page_script.py"))
    assert not set(GEMINI + REPORTS) & set(page)
    for name in set(SUMMARY_COPIES + REPORTS_COPIES) - {"now_th"}:
        assert dump(page[name]) == dump(APP[name]), name
    # now_th ของหน้าเว็บนับเวลาต่อจากเวลาอ่านชีต/เวลาที่ Gemini ตอบ (extract_page.TEXT_CHANGES) — สำเนาใน reports.py เป็นของเดิม
    assert "now_th" in page
