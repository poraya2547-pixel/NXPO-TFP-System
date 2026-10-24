"""ตรวจ contrast ของข้อความทุกหน้า ทั้งเครื่องที่ตั้งธีมสว่างและมืด (ระบบใหม่ล็อกธีมสว่าง — ผลสองธีมต้องผ่านเหมือนกัน)

- เปิด Chrome headless ของเครื่องเอง (โปรไฟล์ชั่วคราว) แล้วเดินหน้าเดียวกับ screens.py: ผู้เยี่ยมชม + คณะวิจัย
- ทุกสถานะรัน contrast_scan.js; ข้อความที่ contrast < 3:1 นับเป็นข้อผิดพลาด ยกเว้นรายการใน KNOWN (สีที่หน้าเดิมออกแบบไว้เอง)
- ล็อกอินคณะวิจัยด้วยบัญชีทดสอบจาก private/local/secrets.test.toml (ไม่ใช่รหัสจริง) ไม่กดปุ่ม Gemini
- ผลเขียนที่ private/verification/<ชุด>/contrast.json ห้ามทับ; exit 1 ถ้าพบข้อผิดพลาด

    /opt/anaconda3/envs/idntwww/bin/python -B tools/refactor/contrast_check.py <ชุด> [URL=http://127.0.0.1:8090]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9231
SCAN = (HERE / "contrast_scan.js").read_text(encoding="utf-8")

# สีที่หน้าเดิมออกแบบไว้เองและต่ำกว่า 3:1 — พบเหมือนกันในแอปเดิม (Streamlit 1.64) ธีมสว่างทุกสถานะ
# (private/verification/contrast-original-r1 เทียบ contrast-after-r5) ไม่ใช่ผลของธีมมืด ไม่แก้ CSS ของเพื่อน (รายงานแยก)
# รูปแบบ (fg, bg) หลังผสมสีแล้ว
KNOWN = {
    ("rgb(255,255,255)", "rgb(249,115,22)"): "หัวตาราง/ปุ่มตัวขาวบน --brand-orange #F97316 (2.80:1)",
    ("rgb(185,192,203)", "rgb(238,242,246)"): "ขีด '-' ช่องว่างในตารางค่าสัมประสิทธิ์ (1.63:1)",
    ("rgb(185,192,203)", "rgb(255,255,255)"): "ขีด '-' ช่องว่างในตารางค่าสัมประสิทธิ์ (1.83:1)",
    ("rgb(185,192,199)", "rgb(255,255,255)"): "ตัวคั่น '·' หน้าทำความรู้จักตัวแปร (1.83:1)",
    ("rgb(22,163,74)", "rgb(238,242,246)"): "ค่าสัมประสิทธิ์สีเขียว --green บนแถวสีเทา (2.93:1)",
    ("rgb(34,197,94)", "rgb(164,209,186)"): "ป้าย +x.x% ใน Dark Mode ของแดชบอร์ดนำเสนอ (1.35:1)",
    ("rgb(91,107,124)", "rgb(59,83,103)"): "ปุ่ม '← กลับ' ใน Dark Mode ของแดชบอร์ดนำเสนอ (1.47:1)",
}


def main(set_name, url):
    sys.path.insert(0, str(REPO / "tools" / "baseline"))
    os.environ["TFP_SCREENS_URL"] = url
    os.environ["TFP_SCREENS_DEVTOOLS"] = f"http://127.0.0.1:{PORT}"
    os.environ["TFP_SCREENS_NEW_SESSION"] = "1"
    secrets = tomllib.loads((REPO / "private" / "local" / "secrets.test.toml").read_text(encoding="utf-8"))
    os.environ["TFP_SCREENS_TEST_USER"] = secrets["RESEARCH_USERNAME"]
    os.environ["TFP_SCREENS_TEST_PASS"] = secrets["RESEARCH_PASSWORD"]
    import safe_io
    import screens

    out = REPO / "private" / "verification" / safe_io.check_name(set_name) / "contrast.json"
    safe_io.ensure_absent([out])
    profile = tempfile.mkdtemp(prefix="tfp-contrast-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                               "--no-first-run", "--no-default-browser-check", "--force-color-profile=srgb", url],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = {"url": url, "min_ratio": 3, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "states": []}
    try:
        for _ in range(100):  # รอจนแท็บแรกโหลด URL แล้ว (screens.CDP หาแท็บจาก URL)
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1).read())
                if any(p.get("url", "").startswith(url) for p in pages):
                    break
            except OSError:
                pass
            time.sleep(0.2)
        for scheme in ("light", "dark"):
            os.environ["TFP_SCREENS_COLOR_SCHEME"] = scheme
            for attempt in range(20):  # Chrome เพิ่งเปิด: รายการแท็บใน /json อาจยังไม่พร้อม
                try:
                    cdp = screens.CDP()
                    break
                except RuntimeError:
                    if attempt == 19:
                        raise
                    time.sleep(0.5)

            def scan(name):
                screens.wait_idle(cdp)
                # ขยาย viewport ให้สูงเท่าเนื้อหา (แบบ screens.Shooter) ทุกข้อความจึงอยู่ในจอสำหรับ elementsFromPoint
                h = cdp.js("""(() => Math.max(
                    (document.querySelector('[data-testid="stMain"]') || document.body).scrollHeight,
                    document.scrollingElement.scrollHeight))()""")
                screens.set_device(cdp, "desktop", min(max(int(h), screens.DEVICES["desktop"]["height"]), screens.MAX_HEIGHT))
                time.sleep(1.0)
                # รอ animation/transition ของหน้าเดิม (การ์ดค่อย ๆ ปรากฏ) เล่นจบ ไม่งั้นได้สีกลางทาง (สูงสุด 5 วินาที)
                cdp.js("""Promise.race([Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity)
                                                   .map(a => a.finished.catch(() => null))),
                                        new Promise(r => setTimeout(r, 5000))])""")
                r = cdp.js(SCAN)
                screens.set_device(cdp, "desktop")
                errors = [x for x in r["low"] if (x["fg"], x["bg"]) not in KNOWN]
                known = [x for x in r["low"] if (x["fg"], x["bg"]) in KNOWN]
                report["states"].append({"scheme": scheme, "page_scheme": r["scheme"], "state": name,
                                         "checked": r["checked"], "errors": errors, "known": known})
                print(f"  {scheme:5s} {name:32s} ตรวจ {r['checked']:4d} ข้อความ  ผิด {len(errors):3d}  รู้แล้ว {len(known)}",
                      flush=True)

            screens.set_device(cdp, "desktop")
            cdp.call("Network.clearBrowserCookies")
            cdp.call("Page.navigate", url=url)
            time.sleep(2)
            screens.wait_idle(cdp)
            scan("01_landing")
            screens.click(cdp, "เข้าใช้งาน (ผู้เยี่ยมชม)")
            scan("02_forecast_before_fetch")
            screens.click(cdp, "คลิกดึงข้อมูลอัตโนมัติ")
            scan("03_forecast_h5")
            screens.expand_all(cdp)
            scan("04_forecast_h5_expanded")
            screens.click(cdp, "สร้างแดชบอร์ดสำหรับนำเสนอ")
            scan("05_exec_dashboard_visitor")
            if not cdp.js("""(() => { const t = document.querySelector('.st-key-exec_dark_mode_toggle input');
                                     if (!t) return false; t.click(); return true; })()"""):
                raise LookupError("ไม่พบสวิตช์ Dark Mode ของแดชบอร์ดนำเสนอ")
            time.sleep(1.0)
            scan("05b_exec_dashboard_dark_toggle")
            cdp.js("document.querySelector('.st-key-exec_dark_mode_toggle input').click()")
            time.sleep(1.0)
            screens.click(cdp, "← กลับ")
            screens.click(cdp, "ทำความรู้จักตัวแปร")
            scan("06_data_vars")
            screens.click(cdp, "คู่มือ & ศัพท์ที่ควรรู้")
            scan("07_manual")
            screens.click(cdp, "เข้าสู่ระบบคณะวิจัย")
            screens.click(cdp, "เข้าสู่ระบบ (คณะวิจัย)")
            scan("08_research_login_form")
            screens.test_login(cdp)
            screens.click(cdp, "สำหรับคณะวิจัยเท่านั้น")
            screens.click(cdp, "คลิกดึงข้อมูลอัตโนมัติ")
            scan("09_research_home")
            screens.expand_all(cdp)
            scan("10_research_home_expanded")
            screens.click(cdp, "จัดการข้อมูลอัตโนมัติ")
            scan("11_data_admin")
            screens.click(cdp, "ตั้งค่าระบบ")
            scan("12_settings")
            screens.click(cdp, "Dashboard พยากรณ์ TFP")
            scan("13_forecast_research")
            screens.click(cdp, "สร้างแดชบอร์ดสำหรับนำเสนอ")
            scan("14_exec_dashboard_research")
            cdp.ws.close()
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)
    # ล็อกธีมสว่าง: เครื่องธีมมืดต้องได้ข้อความ contrast ต่ำชุดเดียวกับธีมสว่างทุกสถานะ
    def low_set(s):
        return sorted((x["text"], x["fg"], x["bg"]) for x in s["errors"] + s["known"])
    by = {(s["scheme"], s["state"]): s for s in report["states"]}
    mismatch = [st for (sch, st), s in by.items() if sch == "light" and low_set(s) != low_set(by[("dark", st)])]
    report["scheme_mismatch"] = mismatch
    for st in mismatch:
        print(f"ผิด ธีมมืดกับสว่างได้ผลต่างกันที่ {st}")
    n_err = sum(len(s["errors"]) for s in report["states"]) + len(mismatch)
    report["error_count"] = n_err
    report["known_notes"] = {f"{fg} on {bg}": note for (fg, bg), note in KNOWN.items()}
    safe_io.write_new(out, json.dumps(report, ensure_ascii=False, indent=1))
    for s in report["states"]:
        for e in s["errors"]:
            print(f"ผิด {s['scheme']}/{s['state']}: {e['ratio']}:1 {e['fg']} บน {e['bg']} [{e['where']}] {e['text']}")
    print(f"ผล: {out.relative_to(REPO)} — ข้อผิดพลาด {n_err} รายการ")
    return 1 if n_err else 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("ใช้: contrast_check.py <ชุด> [URL]")
    try:
        sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "http://127.0.0.1:8090"))
    except (FileExistsError, ValueError, LookupError, RuntimeError, TimeoutError) as e:
        sys.exit(f"หยุด: {e}")
