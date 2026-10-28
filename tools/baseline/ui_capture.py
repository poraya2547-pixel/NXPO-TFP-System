"""Step 1 ส่วน B: เก็บข้อความ ตัวเลข และองค์ประกอบที่แสดงจริงของทุกหน้าในระบบเดิม ด้วย Streamlit AppTest

- รันไฟล์แอปเดิม TFP_App1.3.0.py (ไม่แก้) ด้วย env idntwww และ PYTHONHASHSEED=0
- ข้อมูล: snapshot เดิมผ่าน loader เดิม (replay) ใส่ใน session_state แบบเดียวกับหลังกดดึงข้อมูล
  ไม่กดปุ่มดึงข้อมูลใน AppTest เพราะปุ่มจริงจะต่อ Google Sheets
- รหัสคณะวิจัยและคีย์ Gemini เป็นค่าทดสอบ รันจากโฟลเดอร์ชั่วคราวที่ไม่มี .streamlit/secrets.toml
  จึงไม่โหลดคีย์จริง และไม่กดปุ่มสรุปด้วย Gemini
- แทนเวลาปัจจุบัน (thai_timestamp) ด้วย <เวลาปัจจุบัน> และแทน base64 ด้วย sha1+ความยาว
- รันไฟล์แอปผ่านโฟลเดอร์ทดสอบ (stage.py) หน้าจัดการข้อมูลจึงอ่าน log ชุด baseline ไม่ใช่ fetch_log.csv ของ workspace
- ผลเก็บใน private/baseline/ui/<ชื่อ>/ (มีค่าข้อมูล ไม่ขึ้น git) ห้ามทับชุดเดิม

    PYTHONHASHSEED=0 /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/ui_capture.py <ชื่อใหม่>
"""
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "private" / "baseline" / "ui"
sys.path[:0] = [str(REPO), str(HERE)]
import fingerprint  # noqa: E402
import safe_io  # noqa: E402

FIXED_LOADED_AT = datetime.datetime(2026, 9, 27, 23, 50, 9)  # เวลาอ่าน snapshot (แทน now_th ตอนกดดึง)
TEST_SECRETS = {"GEMINI_API_KEY": "test-gemini-key", "RESEARCH_USERNAME": "test-user", "RESEARCH_PASSWORD": "test-pass"}
TIME_RE = re.compile(r"\d{1,2} \S+ \d{4} เวลา \d{2}:\d{2} น\.")
DATA_URI_RE = re.compile(r"data:([\w/+.-]+);base64,([A-Za-z0-9+/=]+)")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{400,}$")
SHOCKS = [5.0, -2.5]  # นอกจากค่าเริ่มต้น 1.0 ของช่อง shock
# ปุ่มดาวน์โหลดที่ไฟล์มีเวลาปัจจุบันอยู่ข้างใน url (hash ของเนื้อหา) จึงเปลี่ยนทุกนาที
# เนื้อหาไฟล์นี้คือตาราง audit log ที่เก็บ (และตัดเวลา) ไว้ในองค์ประกอบก่อนหน้าแล้ว (TFP_App1.3.0.py:4318-4323)
TIME_BEARING_DOWNLOADS = {"📥 ดาวน์โหลดประวัติการปรับตัวแปร (.csv)"}
SESSION_KEYS = ["page", "portal_role", "research_authenticated", "active_long_run_vars",
                "active_short_run_spec", "exec_dash_horizon", "exec_dash_chosen_var"]


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def scrub(obj):
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str):
        s = DATA_URI_RE.sub(lambda m: f"<data-uri {m.group(1)} sha1={_sha1(m.group(2))} len={len(m.group(2))}>", obj)
        s = TIME_RE.sub("<เวลาปัจจุบัน>", s)
        if BASE64_RE.match(s):
            return f"<bytes sha1={_sha1(s)} len={len(s)}>"
        return s
    return obj


def find_arrow(msg, path="", depth=0):
    """หา field bytes ชื่อ data ทุกตำแหน่งในโครงสร้าง (ข้อมูลตาราง/กราฟแบบ Arrow)"""
    found = []
    if depth > 5:
        return found
    for fd, val in msg.ListFields():
        p = f"{path}.{fd.name}" if path else fd.name
        if fd.type == fd.TYPE_BYTES and fd.name == "data" and val:
            found.append((msg, fd.name, p, val))
        elif fd.type == fd.TYPE_MESSAGE:
            repeated = not hasattr(val, "ListFields")  # repeated field ไม่ใช่ message เดี่ยว
            for i, m in enumerate(val if repeated else [val]):
                found += find_arrow(m, f"{p}[{i}]" if repeated else p, depth + 1)
    return found


def walk(node, path: str, out: list):
    import pyarrow as pa
    from google.protobuf.json_format import MessageToDict

    rec = {"path": path, "type": getattr(node, "type", type(node).__name__)}
    proto = getattr(node, "proto", None)
    if proto is not None:
        copy = type(proto)()
        copy.CopyFrom(proto)
        arrow = {}
        for container, field, p, raw in find_arrow(copy):
            try:
                table = pa.ipc.open_stream(raw).read_all().to_pandas()
                arrow[p] = scrub(fingerprint.canonical(table))
                setattr(container, field, b"")  # เทียบจากค่าที่ถอดแล้ว ไม่ใช่ bytes ดิบ
            except Exception as e:  # ถอดไม่ได้: คง bytes ไว้ (ถูกแทนด้วย sha1) และบันทึกเหตุผล
                arrow[p] = {"decode_error": type(e).__name__}
        rec["proto"] = scrub(MessageToDict(copy, preserving_proto_field_name=True))
        if rec["type"] == "download_button" and rec["proto"].get("label") in TIME_BEARING_DOWNLOADS:
            rec["proto"]["url"] = "<ไฟล์มีเวลาปัจจุบัน>"
        if arrow:
            rec["arrow"] = arrow
    out.append(rec)
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for i in sorted(children):
            walk(children[i], f"{path}/{i}", out)


class Recorder:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.manifest = {}

    def snap(self, at, name: str, seconds: float):
        elements = []
        walk(at.main, "main", elements)
        walk(at.sidebar, "sidebar", elements)
        capture = {
            "name": name,
            "exceptions": [scrub(str(e.value)) for e in at.exception],
            "session": {k: fingerprint.canonical(at.session_state[k]) if k in at.session_state else None
                        for k in SESSION_KEYS},
            "elements": elements,
        }
        text = json.dumps(capture, ensure_ascii=False, sort_keys=True)
        safe_io.write_new(self.out_dir / f"{name}.json", text)
        counts = {}
        for e in elements:
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        self.manifest[name] = {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                               "exceptions": len(capture["exceptions"]), "element_counts": counts,
                               "seconds": round(seconds, 2)}
        print(f"  {name:44s} องค์ประกอบ {len(elements):4d} · exception {len(capture['exceptions'])} · {seconds:5.1f}s",
              flush=True)


def run_step(rec, at, name, action=None):
    t0 = time.perf_counter()
    if action is not None:
        action(at)
    at.run()
    rec.snap(at, name, time.perf_counter() - t0)


def by_label(widgets, prefix, exact=False):
    for w in widgets:
        label = str(w.label)
        if (label == prefix) if exact else label.startswith(prefix):
            return w
    raise LookupError(f"ไม่พบ widget ที่ป้าย{'ตรงกับ' if exact else 'ขึ้นต้นด้วย'} {prefix!r}")


def capture_all(run_name: str):
    import replay
    import stage
    from streamlit.testing.v1 import AppTest

    out_dir = OUT / safe_io.check_name(run_name)
    safe_io.ensure_absent([out_dir])
    df = replay.load_df_from_snapshot()
    rec = Recorder(out_dir)
    app_stage = stage.make_stage(Path.cwd() / "app_stage")  # cwd เป็นโฟลเดอร์ชั่วคราว (ดู __main__)

    def new_app(state):
        at = AppTest.from_file(str(app_stage / stage.APP_FILE), default_timeout=900)
        for k, v in TEST_SECRETS.items():
            at.secrets[k] = v
        for k, v in state.items():
            at.session_state[k] = v
        return at

    def load_data(at):  # สถานะเดียวกับหลังกดดึงข้อมูลสำเร็จ (TFP_App1.3.0.py:3225-3228)
        at.session_state["gsheet_raw_df"] = df.copy()
        at.session_state["gsheet_loaded_at"] = FIXED_LOADED_AT

    # ---------- ผู้เยี่ยมชม ----------
    print("ผู้เยี่ยมชม", flush=True)
    at = new_app({})
    run_step(rec, at, "v01_landing")
    run_step(rec, at, "v02_forecast_before_fetch", lambda a: a.button(key="pick_role_visitor").click())
    run_step(rec, at, "v03_forecast_h5_default", load_data)
    for h in (3, 10, 15):
        run_step(rec, at, f"v04_forecast_h{h}", lambda a, h=h: a.selectbox(key="tfp_forecast_horizon").set_value(h))
    run_step(rec, at, "v05_forecast_h5_again", lambda a: a.selectbox(key="tfp_forecast_horizon").set_value(5))
    # 4c8aa71: ผล backtest แสดงหลังกดปุ่ม (ผลถูกเก็บในไฟล์ cache ใน stage ของรอบนี้ สถานะหลังจากนี้จึงเห็นผลทันที)
    run_step(rec, at, "v05b_backtest_run", lambda a: a.button(key="btn_run_rolling_bt").click())
    slider = at.slider(key="tfp_rolling_mature_threshold")
    lo, hi, default = slider.min, slider.max, slider.value
    for label, v in (("min", lo), ("max", hi), ("default", default)):
        run_step(rec, at, f"v06_rolling_threshold_{label}",
                 lambda a, v=v: a.slider(key="tfp_rolling_mature_threshold").set_value(v))
    for var in ["FDI_GDP", "FEE_GDP", "ln_HDI", "ln_JOUR_GDP", "MKTCOM"]:  # LONG_RUN_VARS ตามลำดับเดิม
        run_step(rec, at, f"v07_scenario_{var}_shock1", lambda a, var=var: a.selectbox(key="dashboard_var_select_lr").set_value(var))
        for s in SHOCKS:
            tag = str(s).replace("-", "m").replace(".", "_")
            run_step(rec, at, f"v07_scenario_{var}_shock{tag}",
                     lambda a, var=var, s=s: a.number_input(key=f"impact_shock_{var}").set_value(s))
    run_step(rec, at, "v08_exec_visitor", lambda a: a.button(key="forecast_goto_exec_dash").click())
    run_step(rec, at, "v09_exec_visitor_presentation", lambda a: a.toggle(key="exec_presentation_toggle").set_value(True))
    run_step(rec, at, "v10_exec_visitor_dark", lambda a: a.toggle(key="exec_dark_mode_toggle").set_value(True))
    run_step(rec, at, "v11_exec_visitor_toggles_off", lambda a: (a.toggle(key="exec_presentation_toggle").set_value(False),
                                                               a.toggle(key="exec_dark_mode_toggle").set_value(False)))
    run_step(rec, at, "v12_back_to_forecast", lambda a: a.button(key="exec_back_to_forecast").click())
    run_step(rec, at, "v13_data_vars", lambda a: a.button(key="nav_main_1_data_vars").click())
    run_step(rec, at, "v14_manual", lambda a: a.button(key="nav_main_2_manual").click())

    # ---------- คณะวิจัย (รหัสทดสอบ ไม่ใช่รหัสจริง) ----------
    print("คณะวิจัย", flush=True)
    at = new_app({})
    run_step(rec, at, "r01_landing")
    load_data(at)
    run_step(rec, at, "r02_login_form", lambda a: a.button(key="toggle_research_login").click())

    def login(a, user, pw):
        by_label(a.text_input, "ชื่อผู้ใช้").input(user)
        by_label(a.text_input, "รหัสผ่าน").input(pw)
        by_label(a.button, "เข้าสู่ระบบ", exact=True).click()

    run_step(rec, at, "r03_login_wrong", lambda a: login(a, "wrong-user", "wrong-pass"))
    run_step(rec, at, "r04_home", lambda a: login(a, TEST_SECRETS["RESEARCH_USERNAME"], TEST_SECRETS["RESEARCH_PASSWORD"]))
    run_step(rec, at, "r05a_vars_remove_mktcom_selected", lambda a: (
        a.multiselect(key="ms_lr_vars").set_value(["FDI_GDP", "FEE_GDP", "ln_HDI", "ln_JOUR_GDP"])))
    run_step(rec, at, "r05b_vars_reason_and_phrase", lambda a: (
        a.text_area(key="var_change_reason").input("ทดสอบ baseline"),
        a.text_input(key="confirm_phrase_input").input("ยืนยันการปรับตัวแปร")))
    run_step(rec, at, "r06_vars_confirmed", lambda a: by_label(a.button, "✅").click())
    run_step(rec, at, "r07_forecast_custom_vars", lambda a: a.button(key="nav_main_0_forecast").click())
    run_step(rec, at, "r08_home_custom_vars", lambda a: a.button(key="nav_sec_0_home").click())
    run_step(rec, at, "r09_vars_reset", lambda a: by_label(a.button, "↩️").click())
    run_step(rec, at, "r10_data_admin", lambda a: a.button(key="nav_sec_1_data_admin").click())
    run_step(rec, at, "r11_settings", lambda a: a.button(key="nav_sec_2_settings").click())
    run_step(rec, at, "r12_forecast", lambda a: a.button(key="nav_main_0_forecast").click())
    run_step(rec, at, "r13_scenario_ln_HDI_shock5", lambda a: a.selectbox(key="dashboard_var_select_lr").set_value("ln_HDI"))
    run_step(rec, at, "r14_scenario_ln_HDI_shock5_set", lambda a: a.number_input(key="impact_shock_ln_HDI").set_value(5.0))
    run_step(rec, at, "r15_exec_research", lambda a: a.button(key="forecast_goto_exec_dash").click())
    run_step(rec, at, "r16_exec_research_presentation", lambda a: a.toggle(key="exec_presentation_toggle").set_value(True))
    run_step(rec, at, "r17_data_vars", lambda a: (a.toggle(key="exec_presentation_toggle").set_value(False),
                                                  a.button(key="exec_back_to_forecast").click()))
    run_step(rec, at, "r18_data_vars_page", lambda a: a.button(key="nav_main_1_data_vars").click())
    run_step(rec, at, "r19_logout", lambda a: a.button(key="nav_logout").click())

    import runtime_info

    safe_io.write_new(out_dir / "manifest.json", json.dumps({
        "run": run_name, "hash_seed": os.environ.get("PYTHONHASHSEED"),
        "fixed_loaded_at": FIXED_LOADED_AT.isoformat(),
        "fetch_log_sha256": hashlib.sha256((app_stage / "fetch_log.csv").read_bytes()).hexdigest(),
        "runtime": runtime_info.runtime_identity(),
        "captures": rec.manifest,
    }, ensure_ascii=False, indent=1))
    return rec.manifest


if __name__ == "__main__":
    if os.environ.get("PYTHONHASHSEED") != "0":
        sys.exit("ต้องรันด้วย PYTHONHASHSEED=0")
    if len(sys.argv) != 2:
        sys.exit("ต้องระบุชื่อชุดใหม่ เช่น ui_capture.py ui-r1")
    try:
        safe_io.ensure_absent([OUT / safe_io.check_name(sys.argv[1])])
    except (FileExistsError, ValueError) as e:
        sys.exit(str(e))
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)  # ไม่มี .streamlit/secrets.toml ในโฟลเดอร์นี้ จึงไม่โหลดคีย์จริง
        manifest = capture_all(sys.argv[1])
    print(f"เก็บแล้ว {len(manifest)} สถานะ · exception รวม {sum(m['exceptions'] for m in manifest.values())}")
