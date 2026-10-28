"""โค้ดหน้าเว็บที่ย้าย (backend/app/page_script.py) ต้องเป็นโค้ดเดิมของ TFP_App1.3.0.py ต่างเฉพาะที่ประกาศไว้

ตรวจโดยไม่เชื่อตัวสร้าง: นิยามที่ถูกลบต้องมีอยู่ (AST เดียวกัน) ในโมดูลปลายทาง ข้อความที่เหลือต้องเท่ากับต้นฉบับ
หลังลบบรรทัดของนิยามเหล่านั้นและแทนข้อความตามรายการที่ประกาศ (แต่ละข้อความพบครั้งเดียว)
"""
import ast
import hashlib
import sys

import parity

REPO = parity.REPO
NEW = REPO / "backend" / "app"
sys.path.insert(0, str(REPO / "tools" / "refactor"))
import extract_page  # noqa: E402

DESTINATIONS = {"core": NEW / "modeling" / "core.py", "charts": NEW / "charts.py", "jobs": NEW / "jobs.py"}
PENDING_STEP7 = {"reports", "summary"}  # รายงาน/Gemini ย้ายใน Step 7 — ตรวจปลายทางเมื่อสร้างโมดูลแล้ว
# ย้ายพร้อมการเปลี่ยนที่ประกาศ (ถอด cache / คืนค่าแทนวางลงหน้า) — ตรวจแล้วใน test_moved_source.py
TRANSFORMED = {"_auto_arima_forecast", "_run_backtest", "_run_rolling_backtest", "_nice_line_chart",
               "_nice_line_chart_with_forecast"}
# 4c8aa71: cache ไฟล์ backtest_cache.pkl ไม่ใช้ในระบบใหม่ — สองชื่อ page_api ทำแทน (อ่านผล worker ใน DB) อีกหกชื่อตัดทิ้ง
WORKER_CACHE = {"page_api", "dropped"}


def dump(n):
    return ast.dump(n, include_attributes=False)


def named(path):
    out = {}
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.FunctionDef):
            out[n.name] = n
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            out[n.targets[0].id] = n
    return out


def test_page_script_is_generated_output():
    src = (REPO / "TFP_App1.3.0.py").read_text(encoding="utf-8")
    assert (NEW / "page_script.py").read_text(encoding="utf-8") == extract_page.build(src)


def test_removed_definitions_exist_unchanged_at_destination():
    src = (REPO / "TFP_App1.3.0.py").read_text(encoding="utf-8")
    original = extract_page.top_level_nodes(src)
    dest = {k: named(p) for k, p in DESTINATIONS.items()}
    for name, where in extract_page.MOVED.items():
        if where in PENDING_STEP7 or where in WORKER_CACHE:
            continue
        node = original[name]
        if name in TRANSFORMED:
            continue
        assert dump(dest[where][name]) == dump(node), f"{name} ใน {where} ไม่ตรงกับต้นฉบับ"


def test_remaining_text_equals_original_except_declared_changes():
    """ตรวจซ้ำอีกทางโดยไม่ใช้ build(): ลบช่วงบรรทัดของนิยามที่ย้าย แล้วแทนข้อความทีละรายการ"""
    src = (REPO / "TFP_App1.3.0.py").read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    drop = set()
    for n in ast.parse(src).body:
        name = getattr(n, "name", None) or (n.targets[0].id if isinstance(n, ast.Assign) and len(n.targets) == 1
                                             and isinstance(n.targets[0], ast.Name) else None)
        if name in extract_page.MOVED:
            first = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
            drop.update(range(first, n.end_lineno + 1))
    expected = "".join(line for i, line in enumerate(lines, start=1) if i not in drop)
    for old, new in extract_page.TEXT_CHANGES:
        assert expected.count(old) == 1, old[:60]
        expected = expected.replace(old, new)
    page = (NEW / "page_script.py").read_text(encoding="utf-8")
    assert page.startswith(extract_page.HEAD)
    assert page[len(extract_page.HEAD):] == expected


def test_no_streamlit_or_original_imports_left():
    tree = ast.parse((NEW / "page_script.py").read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    assert not imported & {"streamlit", "TFP", "data_loader"}


def test_assets_are_byte_copies():
    files = sorted(p.name for p in REPO.glob("*.png")) + [f"fonts/{p.name}" for p in (REPO / "fonts").glob("*")]
    assert files
    for f in files:
        a = hashlib.sha256((REPO / f).read_bytes()).hexdigest()
        b = hashlib.sha256((NEW / "assets" / f).read_bytes()).hexdigest()
        assert a == b, f


def test_backtest_file_cache_replaced_by_worker_results():
    """4c8aa71: ชื่อที่อ่าน/เขียนไฟล์ .pkl ไม่เหลือในหน้า และหน้าใช้ _bt_cache_has/_backtest_with_file_cache ของ page_api"""
    import app.page_api as page_api
    page = (NEW / "page_script.py").read_text(encoding="utf-8")
    tree = ast.parse(page)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in extract_page.BT_CACHE_DROPPED:
        assert name not in used and name not in defined, f"{name} ยังถูกใช้ในหน้า"
    assert "import pickle" not in page  # คอมเมนต์หัวข้อเดิมที่อ้างชื่อไฟล์ยังอยู่ได้ (ไม่ใช่โค้ด)
    for name in extract_page.BT_CACHE_REPLACED:
        assert name not in defined and name in used and callable(getattr(page_api, name))
