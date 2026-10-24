"""ถ่ายภาพหน้าจอระบบเดิม desktop/mobile ผ่าน Chrome DevTools Protocol

- ต่อ Chrome ที่เปิดด้วย --remote-debugging-port=9222 (หน้าต่างที่ผู้ใช้เห็นและล็อกอินเอง)
- แอปเดิมรันผ่าน run_app_snapshot.py (ปุ่มดึงข้อมูลอ่าน snapshot ไม่ใช่ Google Sheets)
- สคริปต์ไม่พิมพ์รหัสผ่าน ไม่กดปุ่มสรุปด้วย Gemini
- ภาพเต็มหน้า: ขยายความสูง viewport ให้เท่าเนื้อหา แล้วถ่ายครั้งเดียว
- ภาพเก็บใน private/baseline/ui/screens/<ชุด>/ ห้ามทับไฟล์เดิม

    python -B tools/baseline/screens.py visitor <ชุด>    # ส่วนที่ไม่ต้องล็อกอิน + หน้าฟอร์มล็อกอิน
    python -B tools/baseline/screens.py research <ชุด>   # หลังผู้ใช้ล็อกอินเองในหน้าต่าง Chrome
"""
import base64
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "private" / "baseline" / "ui" / "screens"
sys.path.insert(0, str(HERE))
import safe_io  # noqa: E402

import os  # noqa: E402

# ค่าเริ่มต้น = แอปเดิม (--server.address 127.0.0.1) กับ Chrome ที่ผู้ใช้เปิด; ระบบใหม่ส่งค่าผ่าน env (Step 4)
APP_URL = os.environ.get("TFP_SCREENS_URL", "http://127.0.0.1:8502")
DEVTOOLS = os.environ.get("TFP_SCREENS_DEVTOOLS", "http://127.0.0.1:9222")
DEVICES = {
    "desktop": {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
    "mobile": {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
}
MAX_HEIGHT = 16000


class CDP:
    def __init__(self):
        from websockets.sync.client import connect

        pages = json.loads(urllib.request.urlopen(f"{DEVTOOLS}/json").read())
        page = next((p for p in pages if p.get("type") == "page" and p.get("url", "").startswith(APP_URL)), None)
        if page is None:
            raise RuntimeError(f"ไม่พบแท็บ {APP_URL} ใน Chrome ที่เปิด remote debugging")
        self.ws = connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=10)
        self.i = 0
        # แท็บเบื้องหลังไม่วาดหน้าจอ (ไม่มี resize/ResizeObserver/rAF) — นำแท็บที่จะถ่ายขึ้นหน้าก่อน
        self.call("Page.bringToFront")

    def call(self, method, **params):
        self.i += 1
        my = self.i
        self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


def wait_idle(cdp, timeout=240):
    """รอจน Streamlit รันสคริปต์เสร็จและความสูงหน้าไม่เปลี่ยน 3 รอบติด"""
    t0, stable, last = time.time(), 0, None
    while time.time() - t0 < timeout:
        state = cdp.js("""(() => {
            const running = !!document.querySelector('[data-testid="stStatusWidget"]')
                || !!document.querySelector('[data-testid="stSpinner"]');
            const main = document.querySelector('[data-testid="stMain"]') || document.body;
            return {running, h: main.scrollHeight, ready: !!document.querySelector('[data-testid="stApp"]')};
        })()""") or {}
        if state.get("ready") and not state.get("running") and state.get("h") == last:
            stable += 1
            if stable >= 3:
                return
        else:
            stable = 0
        last = state.get("h")
        time.sleep(0.7)
    raise TimeoutError("Streamlit ไม่นิ่งภายในเวลาที่กำหนด")


def click(cdp, text, exact=False):
    ok = cdp.js(f"""(() => {{
        const want = {json.dumps(text)};
        const b = [...document.querySelectorAll('button')].find(x => {{
            const t = x.innerText.trim();
            if (x.closest('.st-key-ai_cta_card')) return false;  // ปุ่มสรุปด้วย Gemini ห้ามกด
            return {'t === want' if exact else 't.includes(want)'};
        }});
        if (!b) return false;
        b.scrollIntoView({{block: 'center'}}); b.click(); return true;
    }})()""")
    if not ok:
        raise LookupError(f"ไม่พบปุ่ม {text!r}")
    time.sleep(1.0)
    wait_idle(cdp)


def expand_all(cdp):
    cdp.js("""document.querySelectorAll('[data-testid="stExpander"] details:not([open]) summary')
              .forEach(s => s.click())""")
    time.sleep(1.5)
    wait_idle(cdp)


def set_device(cdp, name, height=None):
    d = dict(DEVICES[name])
    if height:
        d["height"] = height
    cdp.call("Emulation.setDeviceMetricsOverride", **d)
    scheme = os.environ.get("TFP_SCREENS_COLOR_SCHEME")  # Chrome แบบ headless ใช้ธีมตามเครื่อง — กำหนดให้ตรงกับชุดที่เทียบ
    if scheme:
        cdp.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
    time.sleep(1.5)


class Shooter:
    def __init__(self, cdp, set_name):
        self.cdp, self.dir, self.manifest = cdp, OUT / safe_io.check_name(set_name), {}

    def shot(self, name):
        for device in ("desktop", "mobile"):
            set_device(self.cdp, device)
            wait_idle(self.cdp)
            h = self.cdp.js("""(() => Math.max(
                (document.querySelector('[data-testid="stMain"]') || document.body).scrollHeight,
                document.scrollingElement.scrollHeight))()""")
            height = min(max(int(h), DEVICES[device]["height"]), MAX_HEIGHT)
            set_device(self.cdp, device, height)
            time.sleep(2.0)  # ให้กราฟ Vega วาดใหม่ตามขนาด
            png = base64.b64decode(self.cdp.call("Page.captureScreenshot", format="png")["data"])
            path = self.dir / device / f"{name}.png"
            safe_io.write_new(path, png)
            self.manifest[f"{device}/{name}"] = {"sha256": hashlib.sha256(png).hexdigest(), "bytes": len(png),
                                                 "viewport": [DEVICES[device]["width"], height],
                                                 "truncated": int(h) > MAX_HEIGHT}
            print(f"  {device:7s} {name:36s} {DEVICES[device]['width']}x{height}", flush=True)
        set_device(self.cdp, "desktop")

    def save_manifest(self, phase):
        safe_io.write_new(self.dir / f"manifest_{phase}.json",
                          json.dumps({"phase": phase, "captured_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                                      "shots": self.manifest}, ensure_ascii=False, indent=1))


def ensure_new_phase(set_name, phase, names):
    """ภาพและ manifest ของรอบนี้ต้องยังไม่มี รอบที่หยุดกลางทางต้องย้ายออกก่อน ไม่เขียนทับ"""
    d = OUT / safe_io.check_name(set_name)
    safe_io.ensure_absent([d / dev / f"{n}.png" for dev in DEVICES for n in names] + [d / f"manifest_{phase}.json"])


def visitor(set_name):
    ensure_new_phase(set_name, "visitor", ["01_landing", "02_forecast_before_fetch", "03_forecast_h5",
                                           "04_forecast_h5_expanded", "05_exec_dashboard_visitor", "06_data_vars",
                                           "07_manual", "08_research_login_form"])
    cdp = CDP()
    s = Shooter(cdp, set_name)
    set_device(cdp, "desktop")
    if os.environ.get("TFP_SCREENS_NEW_SESSION") == "1":  # ระบบใหม่เก็บ session ใน cookie — เริ่มรอบใหม่ทุกครั้ง
        cdp.call("Network.clearBrowserCookies")
    cdp.call("Page.navigate", url=APP_URL)
    time.sleep(2)
    wait_idle(cdp)
    s.shot("01_landing")
    click(cdp, "เข้าใช้งาน (ผู้เยี่ยมชม)")
    s.shot("02_forecast_before_fetch")
    click(cdp, "คลิกดึงข้อมูลอัตโนมัติ")
    s.shot("03_forecast_h5")
    expand_all(cdp)
    s.shot("04_forecast_h5_expanded")
    click(cdp, "สร้างแดชบอร์ดสำหรับนำเสนอ")
    s.shot("05_exec_dashboard_visitor")
    click(cdp, "← กลับ")
    click(cdp, "ทำความรู้จักตัวแปร")
    s.shot("06_data_vars")
    click(cdp, "คู่มือ & ศัพท์ที่ควรรู้")
    s.shot("07_manual")
    click(cdp, "เข้าสู่ระบบคณะวิจัย")  # ปุ่มเมนูซ้ายพากลับหน้าเลือกบทบาท (app.py:3204-3206)
    click(cdp, "เข้าสู่ระบบ (คณะวิจัย)")  # ปุ่มหน้าแรกที่เปิดฟอร์มล็อกอิน (app.py:3108)
    s.shot("08_research_login_form")
    s.save_manifest("visitor")


def test_login(cdp):
    """เฉพาะระบบใหม่บนเครื่องพัฒนา: ล็อกอินด้วยบัญชีทดสอบจาก env (ไม่ใช่รหัสจริง) — แอปเดิมยังให้ผู้ใช้ล็อกอินเอง"""
    user, pw = os.environ["TFP_SCREENS_TEST_USER"], os.environ["TFP_SCREENS_TEST_PASS"]
    cdp.call("Network.clearBrowserCookies")
    cdp.call("Page.navigate", url=APP_URL)
    time.sleep(2)
    wait_idle(cdp)
    click(cdp, "เข้าสู่ระบบ (คณะวิจัย)")
    ok = cdp.js(f"""(() => {{
        const set = (label, v) => {{
            const el = [...document.querySelectorAll('input')].find(i => (i.getAttribute('aria-label') || '').startsWith(label));
            if (!el) return false;
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v);
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            return true;
        }};
        return set('ชื่อผู้ใช้', {json.dumps(user)}) && set('รหัสผ่าน', {json.dumps(pw)});
    }})()""")
    if not ok:
        raise RuntimeError("ไม่พบช่องชื่อผู้ใช้/รหัสผ่าน")
    click(cdp, "เข้าสู่ระบบ", exact=True)


def research(set_name):
    ensure_new_phase(set_name, "research", ["09_research_home", "10_research_home_expanded", "11_data_admin",
                                            "12_settings", "13_forecast_research", "14_exec_dashboard_research"])
    cdp = CDP()
    s = Shooter(cdp, set_name)
    set_device(cdp, "desktop")
    if os.environ.get("TFP_SCREENS_TEST_USER"):
        test_login(cdp)
    if not cdp.js("[...document.querySelectorAll('button')].some(b => b.innerText.includes('ออกจากระบบคณะวิจัย'))"):
        raise RuntimeError("ยังไม่ได้ล็อกอินคณะวิจัยในหน้าต่าง Chrome")
    set_device(cdp, "desktop")
    wait_idle(cdp)
    click(cdp, "สำหรับคณะวิจัยเท่านั้น")  # ผู้ใช้อาจเปิดหน้าอื่นค้างไว้ เริ่มที่หน้าหลักคณะวิจัยเสมอ
    click(cdp, "คลิกดึงข้อมูลอัตโนมัติ")  # อ่าน snapshot ผ่าน run_app_snapshot.py ไม่ใช่ Google Sheets
    if not cdp.js("document.body.innerText.includes('ดึงข้อมูลล่าสุดเมื่อ')"):
        raise RuntimeError("ดึงข้อมูลจาก snapshot ไม่สำเร็จ")
    s.shot("09_research_home")
    expand_all(cdp)
    s.shot("10_research_home_expanded")
    click(cdp, "จัดการข้อมูลอัตโนมัติ")
    s.shot("11_data_admin")
    click(cdp, "ตั้งค่าระบบ")
    s.shot("12_settings")
    click(cdp, "Dashboard พยากรณ์ TFP")
    s.shot("13_forecast_research")
    click(cdp, "สร้างแดชบอร์ดสำหรับนำเสนอ")
    s.shot("14_exec_dashboard_research")
    s.save_manifest("research")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("visitor", "research"):
        sys.exit("ใช้: screens.py visitor|research <ชุด>")
    try:
        {"visitor": visitor, "research": research}[sys.argv[1]](sys.argv[2])
    except (FileExistsError, ValueError, LookupError, RuntimeError, TimeoutError) as e:
        sys.exit(f"หยุด: {e}")
