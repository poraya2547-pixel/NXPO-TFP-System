"""โค้ดที่ย้ายต้องเป็นโค้ดเดิม: เทียบโครงสร้าง (AST) กับไฟล์ต้นฉบับที่ root ของ workspace (7bf84e4; ก่อน 10 ต.ค. คือ e6aee03)
ตรง ๆ ต่างได้เฉพาะจุดที่ประกาศไว้

- modeling/tfp.py      = TFP.py ทุก byte
- modeling/core.py     = ฟังก์ชัน/ค่าคงที่ตามรายชื่อ ลำดับเดิม ต่างเพียงถอด @st.cache_data(show_spinner=False)
                         และ import ชื่อที่แอปเดิม import จาก TFP ด้วย `from .tfp import` (ตาราง ADF ของ 7bf84e4)
- charts.py            = ตัวสร้างกราฟ ต่างเพียงคืนค่าแทนการวางกราฟ/คำอธิบายลงหน้า Streamlit
- data_loader.py       = loader เดิม ต่างเพียง docstring หัวไฟล์ การ import ที่มาของค่าลับใน _get_client
                         และตัดบล็อก __main__ (ซึ่งต่อ Sheets จริง)
- modeling/scenario.py = สูตรเดียวกับ inline code สองที่ในหน้าเว็บเดิม
ไม่เชื่อตัวสร้างไฟล์ (tools/refactor/extract_core.py) ใช้จากมันเพียงรายชื่อสิ่งที่ย้าย
"""
import ast
import copy
import hashlib
import sys

import parity

REPO = parity.REPO
NEW = REPO / "backend" / "app"
sys.path.insert(0, str(REPO / "tools" / "refactor"))
from extract_core import CHARTS, CORE  # noqa: E402


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def dump(node):
    return ast.dump(node, include_attributes=False)


def named(tree):
    """ฟังก์ชันและการกำหนดค่าชื่อเดียวระดับไฟล์ ชื่อซ้ำถือว่าผิด"""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        else:
            continue
        assert name not in out, f"{name} ถูกนิยามซ้ำ"
        out[name] = node
    return out


def rest(tree):
    return [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.Assign))]


def is_docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


APP_TREE = parse(REPO / "TFP_App1.3.0.py")
APP = named(APP_TREE)
APP_IMPORTS = {dump(n) for n in APP_TREE.body if isinstance(n, (ast.Import, ast.ImportFrom))}


def assert_imports_from_app(tree):
    # ประกาศไว้: ชื่อที่แอปเดิม import จาก TFP ใช้จาก .tfp ได้ (tfp.py = TFP.py ทุก byte — test_tfp_module_is_byte_copy)
    tfp_names = {a.name for n in APP_TREE.body if isinstance(n, ast.ImportFrom) and n.module == "TFP" for a in n.names}
    for n in rest(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "tfp" and n.level == 1 \
                and not any(a.asname for a in n.names) and {a.name for a in n.names} <= tfp_names:
            continue
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            assert dump(n) in APP_IMPORTS, f"import ที่ไม่มีในไฟล์แอปเดิม: {ast.unparse(n)}"


def test_tfp_module_is_byte_copy():
    old = hashlib.sha256((REPO / "TFP.py").read_bytes()).hexdigest()
    new = hashlib.sha256((NEW / "modeling" / "tfp.py").read_bytes()).hexdigest()
    assert old == new


def test_core_is_original_code():
    tree = parse(NEW / "modeling" / "core.py")
    new = named(tree)
    assert list(new) == sorted(CORE, key=lambda n: APP[n].lineno), "ชื่อหรือลำดับไม่ตรงกับไฟล์แอปเดิม"
    for name in CORE:
        orig = APP[name]
        if name in ("_auto_arima_forecast", "_run_backtest", "_run_rolling_backtest"):  # สองชื่อหลังตั้งแต่ 4c8aa71
            assert [ast.unparse(d) for d in orig.decorator_list] == ["st.cache_data(show_spinner=False)"]
            orig = copy.deepcopy(orig)
            orig.decorator_list = []
        assert dump(new[name]) == dump(orig), f"{name} ไม่ตรงกับต้นฉบับ"
    # นอกจากฟังก์ชัน/ค่าคงที่: docstring, import ที่มีในแอปเดิม และ warnings.simplefilter สองบรรทัดเดิม (56-57)
    app_filters = [dump(n) for n in APP_TREE.body if isinstance(n, ast.Expr) and n.lineno in (56, 57)]
    others = rest(tree)
    assert is_docstring(others[0])
    assert [dump(n) for n in others[1:] if isinstance(n, ast.Expr)] == app_filters
    assert all(isinstance(n, (ast.Import, ast.ImportFrom, ast.Expr)) for n in others)
    assert_imports_from_app(tree)


def test_charts_differ_only_in_returning_output():
    tree = parse(NEW / "charts.py")
    new = named(tree)
    assert list(new) == sorted(CHARTS, key=lambda n: APP[n].lineno)
    for name in ("FONT_FAMILY", "_mape_threshold_chart"):
        assert dump(new[name]) == dump(APP[name]), name

    def st_call(node, attr):
        return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and ast.unparse(node.value.func) == f"st.{attr}")

    for name in ("_nice_line_chart", "_nice_line_chart_with_forecast"):
        o, n = APP[name], new[name]
        assert dump(o.args) == dump(n.args) and not o.decorator_list and not n.decorator_list, name

    # _nice_line_chart: st.altair_chart(chart, use_container_width=True) -> return chart
    o, n = APP["_nice_line_chart"].body, new["_nice_line_chart"].body
    assert [dump(x) for x in o[:-1]] == [dump(x) for x in n[:-1]]
    assert ast.unparse(o[-1]) == "st.altair_chart(chart, use_container_width=True)"
    assert ast.unparse(n[-1]) == "return chart"

    # _nice_line_chart_with_forecast: st.altair_chart(...) ถูกตัด และ st.markdown(<HTML>, unsafe_allow_html=True)
    # -> legend_html = <HTML เดิม> แล้ว return chart, legend_html
    o, n = APP["_nice_line_chart_with_forecast"].body, new["_nice_line_chart_with_forecast"].body
    assert [dump(x) for x in o[:-2]] == [dump(x) for x in n[:-2]]
    assert ast.unparse(o[-2]) == "st.altair_chart(chart, use_container_width=True)"
    assert st_call(o[-1], "markdown")
    call = o[-1].value
    assert len(call.args) == 1 and [ast.unparse(k) for k in call.keywords] == ["unsafe_allow_html=True"]
    assert isinstance(n[-2], ast.Assign) and ast.unparse(n[-2].targets[0]) == "legend_html"
    assert dump(n[-2].value) == dump(call.args[0])
    assert ast.unparse(n[-1]) == "return (chart, legend_html)"

    others = rest(tree)
    assert is_docstring(others[0]) and all(isinstance(x, (ast.Import, ast.ImportFrom)) for x in others[1:])
    assert_imports_from_app(tree)


# ความต่างที่ประกาศไว้ของ _get_client (ข้อความแต่ละชิ้นต้องพบในต้นฉบับครั้งเดียว)
GET_CLIENT_CHANGES = [
    ('dict(st.secrets["gcp_service_account"])', 'dict(config.secrets()["gcp_service_account"])'),
    ('from_service_account_file("credentials.json", scopes=SCOPES)',
     "from_service_account_file(config.credentials_file(), scopes=SCOPES)"),
    ("1) จาก st.secrets['gcp_service_account']", "1) จาก TFP_SECRETS_FILE [gcp_service_account]"),
    ('"ตรวจสอบว่า .streamlit/secrets.toml มีตาราง [gcp_service_account] "',
     '"ตรวจสอบว่าไฟล์ค่าลับ (รูปแบบ .streamlit/secrets.toml เดิม) มีตาราง [gcp_service_account] "'),
]


def test_data_loader_differs_only_where_declared():
    old_src = (REPO / "data_loader.py").read_text(encoding="utf-8")
    old_tree, new_tree = ast.parse(old_src), parse(NEW / "data_loader.py")
    old, new = named(old_tree), named(new_tree)
    assert list(old) == list(new)
    for name in old:
        if name != "_get_client":
            assert dump(old[name]) == dump(new[name]), name
    seg = ast.get_source_segment(old_src, old["_get_client"])
    for a, b in GET_CLIENT_CHANGES:
        assert seg.count(a) == 1, a
        seg = seg.replace(a, b)
    assert dump(ast.parse(seg).body[0]) == dump(new["_get_client"])

    def imports(tree):
        return [ast.unparse(n) for n in rest(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]

    old_imp, new_imp = imports(old_tree), imports(new_tree)
    assert [i for i in old_imp if i not in ("import streamlit as st",
                                            "from TFP import RAW_TO_MODEL, PERCENT_VARS, RDH_SOURCE")] \
        == [i for i in new_imp if i not in ("from . import config",
                                            "from .modeling.tfp import RAW_TO_MODEL, PERCENT_VARS, RDH_SOURCE")]
    assert "from TFP import RAW_TO_MODEL, PERCENT_VARS, RDH_SOURCE" in old_imp
    assert "from .modeling.tfp import RAW_TO_MODEL, PERCENT_VARS, RDH_SOURCE" in new_imp
    # ต้นฉบับมีบล็อก if __name__ == "__main__" ท้ายไฟล์ (ต่อ Sheets จริง) ไฟล์ใหม่ไม่มี
    assert [ast.unparse(n.test) for n in rest(old_tree) if isinstance(n, ast.If)] == ["__name__ == '__main__'"]
    assert not [n for n in rest(new_tree) if isinstance(n, ast.If)]


class _Rename(ast.NodeTransformer):
    def __init__(self, names, result=None):
        self.names, self.result = names, result

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id=self.names.get(node.id, node.id), ctx=node.ctx), node)

    def visit_Assign(self, node):
        if self.result and ast.unparse(node.targets[0]) == self.result:
            return ast.copy_location(ast.Return(value=self.visit(node.value)), node)
        return self.generic_visit(node)


def _find_if(test_src):
    found = [n for n in ast.walk(APP_TREE) if isinstance(n, ast.If) and ast.unparse(n.test) == test_src]
    assert len(found) == 1, (test_src, len(found))
    return found[0]


def _branches(if_node):
    """[(เงื่อนไข, body)] ของ if / elif / else"""
    out, node = [], if_node
    while True:
        out.append((node.test, node.body))
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
        else:
            out.append((None, node.orelse))
            return out


def test_scenario_formula_is_the_inline_code():
    fn = named(parse(NEW / "modeling" / "scenario.py"))["scenario_pct_effect"]
    assert is_docstring(fn.body[0]) and len(fn.body) == 2
    new_if = fn.body[1]

    # แดชบอร์ดนำเสนอ 5830-5837: if/elif/else ทั้งก้อน เปลี่ยนชื่อตัวแปรและ scenario_pct_effect = X -> return X
    exec_if = _find_if("scenario_var.startswith('ln_')")
    renamed = _Rename({"scenario_var": "var", "_coef": "coef", "scenario_shock": "shock"},
                      result="scenario_pct_effect").visit(copy.deepcopy(exec_if))
    assert dump(renamed) == dump(new_if)

    # หน้าพยากรณ์: is_log = chosen_var.startswith("ln_") (5109) และ pct_effect สามแบบ (5187 / 5201 / 5214)
    is_log = [n for n in ast.walk(APP_TREE) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "is_log"]
    assert len(is_log) == 1
    page = _branches(_find_if("is_log"))
    mine = _branches(new_if)
    assert len(page) == len(mine) == 3
    rename = _Rename({"chosen_var": "var"})
    assert dump(rename.visit(copy.deepcopy(is_log[0].value))) == dump(mine[0][0])
    assert dump(rename.visit(copy.deepcopy(page[1][0]))) == dump(mine[1][0])
    for (_, body), (_, my_body) in zip(page, mine):
        effect = [n for n in body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "pct_effect"]
        assert len(effect) == 1 and len(my_body) == 1 and isinstance(my_body[0], ast.Return)
        assert dump(effect[0].value) == dump(my_body[0].value)
