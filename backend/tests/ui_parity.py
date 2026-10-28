"""เกณฑ์ A ของหน้าเว็บ: รันโค้ดหน้าที่ย้าย (page_script.py ผ่าน ui.PageRun) ตามลำดับการกระทำเดียวกับ
tools/baseline/ui_capture.py แล้วเทียบกับผลเก็บหน้าจอ 52 สถานะของโค้ดต้นฉบับบน runtime เดียวกัน

- ข้อมูล: snapshot เดิมผ่าน loader ที่ย้าย ใส่เป็นข้อมูลของ session แบบเดียวกับ ui_capture (ไม่กดดึงจริง)
- รหัสคณะวิจัย/คีย์ Gemini เป็นค่าทดสอบชุดเดียวกับ ui_capture · log การดึงข้อมูลใช้ชุด baseline
- เทียบทุก element ตามตำแหน่ง: ชนิด ข้อความ/HTML (แทนเวลาปัจจุบันและ base64 แบบเดียวกับตอนเก็บ),
  ป้าย/ตัวเลือก/ค่าเริ่มต้นของ widget, กล่อง/คอลัมน์, Vega-Lite spec และข้อมูลกราฟ, ตาราง, ไฟล์ดาวน์โหลด
  (คำนวณรหัสไฟล์แบบ Streamlit จากเนื้อไฟล์จริง) และค่า session ที่ ui_capture เก็บ
- widget id: เทียบเฉพาะ key ที่ผู้เขียนตั้ง (hash ของ Streamlit ขึ้นกับ path ไฟล์)

    PYTHONHASHSEED=0 python -B -P backend/tests/ui_parity.py <ชื่อผล> [โฟลเดอร์ผล]
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import parity  # noqa: E402  (ตั้ง sys.path ของ backend และ tools/baseline)

from app import data_loader, page_runner  # noqa: E402
from app.store_memory import MemoryStore  # noqa: E402

REPO = parity.REPO
UI_OUT = REPO / "private" / "baseline" / "ui"
TEST_SECRETS = {"GEMINI_API_KEY": "test-gemini-key", "RESEARCH_USERNAME": "test-user", "RESEARCH_PASSWORD": "test-pass"}
FIXED_LOADED_AT = datetime.datetime(2026, 9, 27, 23, 50, 9)   # ui_capture.FIXED_LOADED_AT
SHOCKS = [5.0, -2.5]                                          # ui_capture.SHOCKS
FETCH_LOG = REPO / "private" / "baseline" / "logs" / "fetch_log_baseline.csv"
SESSION_KEYS = ["page", "portal_role", "research_authenticated", "active_long_run_vars",
                "active_short_run_spec", "exec_dash_horizon", "exec_dash_chosen_var"]
TIME_BEARING_DOWNLOADS = {"📥 ดาวน์โหลดประวัติการปรับตัวแปร (.csv)"}

# ----- แทนค่าที่เปลี่ยนทุกครั้ง แบบเดียวกับ tools/baseline/ui_capture.scrub -----
TIME_RE = re.compile(r"\d{1,2} \S+ \d{4} เวลา \d{2}:\d{2} น\.")
DATA_URI_RE = re.compile(r"data:([\w/+.-]+);base64,([A-Za-z0-9+/=]+)")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{400,}$")


def scrub(obj):
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        s = DATA_URI_RE.sub(lambda m: f"<data-uri {m.group(1)} sha1={hashlib.sha1(m.group(2).encode()).hexdigest()} "
                                      f"len={len(m.group(2))}>", obj)
        s = TIME_RE.sub("<เวลาปัจจุบัน>", s)
        if BASE64_RE.match(s):
            return f"<bytes sha1={hashlib.sha1(s.encode()).hexdigest()} len={len(s)}>"
        return s
    return obj


# ===================== ขับหน้าเว็บตามลำดับของ ui_capture =====================
class Driver:
    def __init__(self, store: MemoryStore, dataset_id: int):
        self.store, self.dataset_id = store, dataset_id
        self.state: dict = {}
        self.result = None

    def run(self, event=None):
        self.result = page_runner.run(self.store, "harness", self.state, event, TEST_SECRETS)
        self.state = self.result["state"]

    @property
    def tree(self):
        return self.result["tree"]

    def values(self):
        return page_runner.codec.decode(self.state["values"]) if self.state.get("values") else {}

    def load_data(self):  # ui_capture.load_data: ข้อมูลชีต + เวลาที่ดึงแบบตรึง
        vals = self.values()
        vals["gsheet_loaded_at"] = FIXED_LOADED_AT
        self.state = dict(self.state, values=page_runner.codec.encode(vals), dataset_id=self.dataset_id)

    def nodes(self):
        out = []

        def walk(n):
            out.append(n)
            for c in n.get("children", []):
                walk(c)
        walk(self.tree["main"])
        walk(self.tree["sidebar"])
        return out

    def widget(self, wid):
        found = [n for n in self.nodes() if n.get("id") == wid]
        assert len(found) == 1, f"ไม่พบ widget {wid}"
        return found[0]

    def by_label(self, type_, prefix, exact=False):
        for n in self.nodes():
            if n["type"] == type_ and ((n["label"] == prefix) if exact else str(n["label"]).startswith(prefix)):
                return n
        raise LookupError(f"ไม่พบ {type_} ป้าย {prefix!r}")

    def option_index(self, wid, value):
        return self.result["options"][wid].index(value)


def drive(df) -> dict:
    """คืน {ชื่อสถานะ: (tree, session values, downloads)} ตามลำดับเดียวกับ ui_capture.capture_all"""
    fetch_rows = list(csv.DictReader(FETCH_LOG.open(encoding="utf-8-sig", newline="")))
    store = MemoryStore(fetch_log=fetch_rows)
    dataset_id = store.add_dataset(df)
    states = {}

    def snap(d, name):
        states[name] = (d.tree, d.values(), store)

    def step(d, name, event=None):
        d.run(event)
        snap(d, name)

    click = lambda wid: {"trigger": wid}  # noqa: E731

    # ---------- ผู้เยี่ยมชม ----------
    d = Driver(store, dataset_id)
    step(d, "v01_landing")
    step(d, "v02_forecast_before_fetch", click("pick_role_visitor"))
    d.load_data()
    step(d, "v03_forecast_h5_default")
    for h in (3, 10, 15):
        step(d, f"v04_forecast_h{h}", {"values": {"tfp_forecast_horizon": d.option_index("tfp_forecast_horizon", h)}})
    step(d, "v05_forecast_h5_again", {"values": {"tfp_forecast_horizon": d.option_index("tfp_forecast_horizon", 5)}})
    step(d, "v05b_backtest_run", click("btn_run_rolling_bt"))  # 4c8aa71 (ui_capture เดียวกัน)
    slider = d.widget("tfp_rolling_mature_threshold")
    for label, v in (("min", slider["min"]), ("max", slider["max"]), ("default", slider["value"])):
        step(d, f"v06_rolling_threshold_{label}", {"values": {"tfp_rolling_mature_threshold": v}})
    for var in ["FDI_GDP", "FEE_GDP", "ln_HDI", "ln_JOUR_GDP", "MKTCOM"]:
        step(d, f"v07_scenario_{var}_shock1",
             {"values": {"dashboard_var_select_lr": d.option_index("dashboard_var_select_lr", var)}})
        for s in SHOCKS:
            tag = str(s).replace("-", "m").replace(".", "_")
            step(d, f"v07_scenario_{var}_shock{tag}", {"values": {f"impact_shock_{var}": s}})
    step(d, "v08_exec_visitor", click("forecast_goto_exec_dash"))
    step(d, "v09_exec_visitor_presentation", {"values": {"exec_presentation_toggle": True}})
    step(d, "v10_exec_visitor_dark", {"values": {"exec_dark_mode_toggle": True}})
    step(d, "v11_exec_visitor_toggles_off", {"values": {"exec_presentation_toggle": False,
                                                        "exec_dark_mode_toggle": False}})
    step(d, "v12_back_to_forecast", click("exec_back_to_forecast"))
    step(d, "v13_data_vars", click("nav_main_1_data_vars"))
    step(d, "v14_manual", click("nav_main_2_manual"))

    # ---------- คณะวิจัย (รหัสทดสอบ) ----------
    d = Driver(store, dataset_id)
    step(d, "r01_landing")
    d.load_data()
    step(d, "r02_login_form", click("toggle_research_login"))

    def login(user, pw):
        return {"trigger": d.by_label("button", "เข้าสู่ระบบ", exact=True)["id"],
                "values": {d.by_label("text_input", "ชื่อผู้ใช้")["id"]: user,
                           d.by_label("text_input", "รหัสผ่าน")["id"]: pw}}

    step(d, "r03_login_wrong", login("wrong-user", "wrong-pass"))
    step(d, "r04_home", login(TEST_SECRETS["RESEARCH_USERNAME"], TEST_SECRETS["RESEARCH_PASSWORD"]))
    keep = ["FDI_GDP", "FEE_GDP", "ln_HDI", "ln_JOUR_GDP"]
    step(d, "r05a_vars_remove_mktcom_selected",
         {"values": {"ms_lr_vars": [d.option_index("ms_lr_vars", v) for v in keep]}})
    step(d, "r05b_vars_reason_and_phrase", {"values": {"var_change_reason": "ทดสอบ baseline",
                                                       "confirm_phrase_input": "ยืนยันการปรับตัวแปร"}})
    step(d, "r06_vars_confirmed", click(d.by_label("button", "✅")["id"]))
    step(d, "r07_forecast_custom_vars", click("nav_main_0_forecast"))
    step(d, "r08_home_custom_vars", click("nav_sec_0_home"))
    step(d, "r09_vars_reset", click(d.by_label("button", "↩️")["id"]))
    step(d, "r10_data_admin", click("nav_sec_1_data_admin"))
    step(d, "r11_settings", click("nav_sec_2_settings"))
    step(d, "r12_forecast", click("nav_main_0_forecast"))
    step(d, "r13_scenario_ln_HDI_shock5",
         {"values": {"dashboard_var_select_lr": d.option_index("dashboard_var_select_lr", "ln_HDI")}})
    step(d, "r14_scenario_ln_HDI_shock5_set", {"values": {"impact_shock_ln_HDI": 5.0}})
    step(d, "r15_exec_research", click("forecast_goto_exec_dash"))
    step(d, "r16_exec_research_presentation", {"values": {"exec_presentation_toggle": True}})
    step(d, "r17_data_vars", {"trigger": "exec_back_to_forecast", "values": {"exec_presentation_toggle": False}})
    step(d, "r18_data_vars_page", click("nav_main_1_data_vars"))
    step(d, "r19_logout", click("nav_logout"))
    return states


# ===================== แปลงสองฝั่งเป็นรูปแบบเดียวกันแล้วเทียบ =====================
def _key_of_capture(wid):
    return wid.split("-", 2)[2] if wid else None


def _key_of_mine(n):
    wid = n.get("id")
    if wid is None:
        return None
    if wid.startswith("$$auto-"):
        return "None"
    return wid


def _label_vis(v):
    return "visible" if not v else str(v.get("value", "VISIBLE")).lower()


def _scalar(v):
    if v is None or (isinstance(v, float) and v != v) or v == "nan":
        return "nan"
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v).hex() if isinstance(v, float) else v
    return str(v)


def _norm_spec(spec):
    """แทนชื่อ dataset ด้วยลำดับที่พบ ตัด datasets ออกจาก spec"""
    names = []

    def walk(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k == "datasets":
                    continue
                if k == "data" and isinstance(v, dict) and set(v) == {"name"}:
                    if v["name"] not in names:
                        names.append(v["name"])
                    out[k] = {"name": f"<data{names.index(v['name'])}>"}
                else:
                    out[k] = walk(v)
            return out
        if isinstance(o, list):
            return [walk(x) for x in o]
        return o

    return walk(spec), names


def capture_view(e: dict) -> tuple:
    t, p = e["type"], e.get("proto") or {}
    if t in ("main", "sidebar"):
        return t, {}
    if t in ("markdown", "caption"):
        return t, {"body": p.get("body", ""), "allow_html": bool(p.get("allow_html"))}
    if t in ("info", "success", "warning", "error"):
        return t, {"body": p.get("body", ""), "icon": p.get("icon")}
    if t == "button":
        return t, {"label": p["label"], "kind": p.get("type"), "icon": p.get("icon"), "help": p.get("help"),
                   "disabled": bool(p.get("disabled")), "form_id": p.get("form_id"),
                   "submitter": bool(p.get("is_form_submitter")), "key": _key_of_capture(p.get("id"))}
    if t == "download_button":
        return t, {"label": p["label"], "kind": p.get("type"), "key": _key_of_capture(p.get("id")),
                   "file": p.get("url", "").rsplit("/", 1)[-1] if p.get("label") not in TIME_BEARING_DOWNLOADS
                   else "<time-bearing>"}
    if t in ("selectbox", "multiselect"):
        return t, {"label": p["label"], "options": p.get("options", []), "default": p.get("default"),
                   "help": p.get("help"), "label_visibility": _label_vis(p.get("label_visibility")),
                   "placeholder": p.get("placeholder"), "key": _key_of_capture(p.get("id"))}
    if t == "number_input":
        return t, {"label": p["label"], "default": p.get("default"), "min": p.get("min"), "max": p.get("max"),
                   "step": p.get("step"), "format": p.get("format"), "data_type": p.get("data_type"),
                   "help": p.get("help"), "key": _key_of_capture(p.get("id"))}
    if t == "slider":
        return t, {"label": p["label"], "default": p.get("default"), "min": p.get("min"), "max": p.get("max"),
                   "step": p.get("step"), "format": p.get("format"), "help": p.get("help"),
                   "key": _key_of_capture(p.get("id"))}
    if t == "toggle":
        return t, {"label": p["label"], "default": bool(p.get("default")), "help": p.get("help"),
                   "label_visibility": _label_vis(p.get("label_visibility")), "key": _key_of_capture(p.get("id"))}
    if t in ("text_input", "text_area"):
        return t, {"label": p["label"], "default": p.get("default", ""), "password": p.get("type") == "PASSWORD",
                   "placeholder": p.get("placeholder"), "form_id": p.get("form_id"),
                   "label_visibility": _label_vis(p.get("label_visibility")), "key": _key_of_capture(p.get("id"))}
    if t == "expander":
        return t, {"label": p["label"], "expanded": bool(p.get("expanded"))}
    if t == "flex_container":
        fc = p.get("flex_container", {})
        return t, {"direction": fc.get("direction"), "border": bool(fc.get("border")),
                   "key": _key_of_capture(p.get("id"))}
    if t == "column":
        return t, {"weight": p.get("weight")}
    if t == "form":
        return t, {"form_id": p["form"]["form_id"], "border": bool(p["form"].get("border"))}
    if t == "vega_lite_chart":
        spec, names = _norm_spec(json.loads(p["spec"]))
        arrow = e.get("arrow", {})
        data = {}
        for i, ds in enumerate(p.get("datasets", [])):
            table = arrow.get(f"datasets[{i}].data.data")
            if ds.get("name") in names:
                data[f"<data{names.index(ds['name'])}>"] = _canon_table(table)
        return t, {"spec": spec, "data": data, "theme": p.get("theme"),
                   "use_container_width": bool(p.get("use_container_width"))}
    if t == "dataframe":
        return t, {"table": _canon_table(next(iter(e.get("arrow", {}).values()), None))}
    return t, {"unknown_proto": sorted(p)}


def _canon_table(t):
    """ตารางจาก ui_capture (fingerprint.canonical ของ DataFrame) → (คอลัมน์, แถว)"""
    if t is None:
        return None
    rows = [[_scalar(float.fromhex(v) if isinstance(v, str) and v.startswith(("0x", "-0x")) else v) for v in r]
            for r in t["values"]]
    return [str(c) for c in t["columns"]], rows


def mine_view(n: dict, downloads: dict) -> tuple:
    t = n["type"]
    if t in ("main", "sidebar"):
        return t, {}
    if t == "markdown":
        kind = "caption" if n["kind"] == "caption" else "markdown"
        return kind, {"body": n["body"], "allow_html": n["allow_html"]}
    if t == "alert":
        return n["kind"], {"body": n["body"], "icon": n.get("icon")}
    if t == "button":
        return t, {"label": n["label"], "kind": n["kind"], "icon": n.get("icon"), "help": n.get("help"),
                   "disabled": n["disabled"], "form_id": n.get("form_id"), "submitter": bool(n.get("is_form_submitter")),
                   "key": _key_of_mine(n)}
    if t == "download_button":
        from streamlit.runtime.media_file_storage import MediaFileKind  # noqa: F401  (ยืนยันว่าใช้ Streamlit ชุดเดียวกัน)
        from streamlit.runtime.memory_media_file_storage import _calculate_file_id, get_extension_for_mimetype
        data, file_name, mime = downloads[n["ref"]]
        file = "<time-bearing>" if n["label"] in TIME_BEARING_DOWNLOADS else (
            _calculate_file_id(data, mime, file_name) + get_extension_for_mimetype(mime))
        return t, {"label": n["label"], "kind": n["kind"], "key": _key_of_mine(n), "file": file}
    if t in ("selectbox", "multiselect"):
        return t, {"label": n["label"], "options": n["options"], "default": n["default"], "help": n.get("help"),
                   "label_visibility": n["label_visibility"], "placeholder": n.get("placeholder"),
                   "key": _key_of_mine(n)}
    if t == "number_input":
        big = 1.7976931348623157e308
        return t, {"label": n["label"], "default": n["default"], "min": -big if n["min"] is None else n["min"],
                   "max": big if n["max"] is None else n["max"], "step": n["step"], "format": n["format"],
                   "data_type": "INT" if n["int"] else "FLOAT", "help": n.get("help"), "key": _key_of_mine(n)}
    if t == "slider":
        return t, {"label": n["label"], "default": [float(n["default"])], "min": float(n["min"]),
                   "max": float(n["max"]), "step": float(n["step"]), "format": n["format"], "help": n.get("help"),
                   "key": _key_of_mine(n)}
    if t == "toggle":
        return t, {"label": n["label"], "default": n["default"], "help": n.get("help"),
                   "label_visibility": n["label_visibility"], "key": _key_of_mine(n)}
    if t in ("text_input", "text_area"):
        return t, {"label": n["label"], "default": n["default"], "password": n.get("input_type") == "password",
                   "placeholder": n.get("placeholder"), "form_id": n.get("form_id"),
                   "label_visibility": n["label_visibility"], "key": _key_of_mine(n)}
    if t == "expander":
        return t, {"label": n["label"], "expanded": n["expanded"]}
    if t == "container":
        return "flex_container", {"direction": "VERTICAL", "border": n["border"], "key": n.get("key")}
    if t == "columns":
        return "flex_container", {"direction": "HORIZONTAL", "border": n["border"], "key": None}
    if t == "column":
        return t, {"weight": n["weight"]}
    if t == "form":
        return t, {"form_id": n["form_id"], "border": n["border"]}
    if t == "vega_lite_chart":
        spec, names = _norm_spec(n["spec"])
        data = {}
        for name, rows in (n["spec"].get("datasets") or {}).items():
            if name in names and rows:
                cols = list(rows[0])
                data[f"<data{names.index(name)}>"] = (cols, [[_scalar(r.get(c)) for c in cols] for r in rows])
        return t, {"spec": spec, "data": data, "theme": n["theme"], "use_container_width": n["use_container_width"]}
    if t == "dataframe":
        return t, {"table": (n["columns"], [[_scalar(v) for v in r] for r in n["rows"]])}
    return t, {"unexpected": True}


def flatten_mine(tree, downloads):
    out = []

    def walk(n, path):
        out.append((path,) + mine_view(n, downloads))
        for i, c in enumerate(n.get("children", [])):
            walk(c, f"{path}/{i}")
    walk(tree["main"], "main")
    walk(tree["sidebar"], "sidebar")
    return out


def flatten_capture(capture):
    return [(e["path"],) + capture_view(e) for e in capture["elements"]]


def compare_state(cap: dict, tree: dict, values: dict, downloads: dict) -> list:
    """คืนรายการความต่าง (ว่าง = ตรงทุก element และค่า session)"""
    diffs = []
    if cap.get("exceptions"):
        diffs.append(f"หลักฐานมี exception {cap['exceptions']}")
    mine = scrub(flatten_mine(tree, downloads))
    ref = scrub(flatten_capture(cap))
    for i in range(max(len(mine), len(ref))):
        a = list(ref[i]) if i < len(ref) else None
        b = list(mine[i]) if i < len(mine) else None
        if a is None or b is None or list(a) != b:
            d = parity.first_difference(parity.fingerprint.canonical(a), parity.fingerprint.canonical(b))
            diffs.append(f"element #{i} {a[0] if a else b[0]}: {d}")
            break
    for k in SESSION_KEYS:
        want = cap["session"].get(k)
        got = parity.fingerprint.canonical(values[k]) if k in values else None
        if want != got:
            diffs.append(f"session {k}: หลักฐาน {want} · ใหม่ {got}")
    return diffs


def reference_states(ref_dir: Path) -> dict:
    """หน้าจออ้างอิงของ runtime นี้ (ตรวจ hash ของ manifest และไฟล์ทุกสถานะ)"""
    import ui_compare
    from compare_runs import check_runtime

    cond = json.loads((ref_dir / "ui_conditions.json").read_text(encoding="utf-8"))
    rt = json.loads((ref_dir / "runtime.json").read_text(encoding="utf-8"))
    name = cond["reference"]["run"]
    sha = hashlib.sha256((UI_OUT / name / "manifest.json").read_bytes()).hexdigest()
    if sha != cond["reference"]["manifest_sha256"]:
        raise RuntimeError("ชุดหน้าจออ้างอิงไม่ใช่ชุดที่ตรึงไว้")
    manifest, states = ui_compare.load_run(name, UI_OUT)
    bad = [t for ok, t in check_runtime(manifest, rt, "อ้างอิง", is_reference=True) if not ok]
    if bad:
        raise RuntimeError("; ".join(bad))
    if sorted(states) != sorted(cond["states"]):
        raise RuntimeError("สถานะในชุดอ้างอิงไม่ครบ")
    for s, (h, _) in states.items():
        if manifest["captures"][s]["sha256"] != h:
            raise RuntimeError(f"hash ของ {s} ไม่ตรง manifest")
    return {s: c for s, (_, c) in states.items()}, cond


def load_snapshot_df():
    tabs = parity.replay.load_tabs()
    real = data_loader._get_client
    data_loader._get_client = lambda: parity.replay._FakeClient(tabs)
    try:
        return data_loader.load_data_gsheet()
    finally:
        data_loader._get_client = real


def run_all() -> tuple[dict, dict]:
    ref_dir = parity.reference_set()
    if ref_dir is None:
        raise RuntimeError("runtime นี้ไม่มีชุด reference ที่ตรึงไว้")
    refs, cond = reference_states(ref_dir)
    states = drive(load_snapshot_df())
    results = {}
    for name in cond["states"]:
        tree, values, store = states[name]
        results[name] = compare_state(refs[name], tree, values, store._downloads_by_ref())
    return results, {"reference_set": str(ref_dir.relative_to(REPO)), "reference_run": cond["reference"]["run"]}


def main(name: str, out_dir: Path) -> int:
    import safe_io

    if os.environ.get("PYTHONHASHSEED") != "0":
        sys.exit("ต้องรันด้วย PYTHONHASHSEED=0")
    out = Path(out_dir) / f"ui_parity_{safe_io.check_name(name)}.json"
    safe_io.ensure_absent([out])
    results, meta = run_all()
    ok = sum(1 for d in results.values() if not d)
    safe_io.write_new(out, json.dumps(dict(meta, run=name, results=results), ensure_ascii=False, indent=1))
    for s, d in results.items():
        print(("ตรง     " if not d else "ต่าง    ") + s + "".join(f"\n      {x}" for x in d))
    print(f"\nสรุป: ตรง {ok}/{len(results)} สถานะ · ชุด {meta['reference_set']} ({meta['reference_run']}) · ผล {out}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("ใช้: ui_parity.py <ชื่อผล> [โฟลเดอร์ผล]")
    sys.exit(main(sys.argv[1], Path(sys.argv[2]) if len(sys.argv) == 3 else REPO / "private" / "verification"))
