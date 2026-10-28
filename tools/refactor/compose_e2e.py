"""ทดสอบระบบที่รันด้วย docker compose จริงผ่าน HTTP (ไม่ใช่ TestClient) — Step 5

1. ผู้เยี่ยมชมกดดึงข้อมูล → job ใน worker container → ผลแสดงในหน้า (ข้อมูลชีตจาก snapshot: TFP_SHEETS_FIXTURE ของ compose)
   เวลา "ดึงข้อมูลล่าสุดเมื่อ" = เวลาที่ worker อ่านชีตเสร็จ (ผลของงานใน DB) แผน §9A
2. รีสตาร์ตทุก service → session/ข้อมูล/ผลยังอยู่ (cookie เดิมใช้ต่อได้ ไม่ได้ session ใหม่)
3. ฆ่า worker ระหว่างงานดึงข้อมูล (session ใหม่) → เมื่อ lease หมด งานถูกปิดเป็น "ล้มเหลว" (ดึงชีตไม่เรียกซ้ำเอง)
   หน้าแสดงข้อความเดิม แล้วผู้ใช้กดดึงใหม่ได้สำเร็จ
4. ฆ่า worker ระหว่างงานคำนวณ series ที่หน้าเปิดแล้วต้องใช้ (session เดิมที่กดปุ่มเริ่มการทดสอบย้อนหลังไว้ในข้อ 1) → งานกลับเข้าคิวและทำซ้ำจนสำเร็จ หน้าแสดงผล
ข้อ 3–4 ลบผลคำนวณที่เก็บไว้ใน DB ของ compose บนเครื่องพัฒนา (ข้อมูลทดสอบจาก snapshot) เพื่อให้งานต้องคำนวณนานพอจะฆ่า worker ระหว่างทำ
ระหว่างรอ ตัวทดสอบส่ง resume เมื่องานที่หน้ารอจบแล้วแบบเดียวกับหน้าเว็บ (frontend/src/App.tsx)

ผลเขียนที่ private/verification/<ชื่อ>/report.txt (ไม่มี token/cookie) ห้ามทับ

    /opt/anaconda3/envs/idntwww/bin/python -B tools/refactor/compose_e2e.py <ชื่อผล>
"""
import datetime
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = os.environ.get("TFP_E2E_URL", "http://127.0.0.1:8090")
COMPOSE = ["docker", "compose", "-p", os.environ.get("TFP_COMPOSE_PROJECT", "tfp"),
           "--env-file", os.environ.get("TFP_COMPOSE_ENV", str(REPO / "private" / "local" / "env")),
           "-f", str(REPO / "deploy" / "compose.yaml")]
LOG: list = []


def say(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    LOG.append(line)
    print(line, flush=True)


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None
        self.last_set_cookie = None

    def _send(self, req):
        with self.http.open(req, timeout=120) as r:
            self.last_set_cookie = r.headers.get("Set-Cookie")
            return r.status, json.loads(r.read().decode("utf-8"))

    def get(self, path):
        status, body = self._send(urllib.request.Request(BASE + path))
        if "csrf_token" in body:
            self.csrf = body["csrf_token"]
        return status, body

    def post(self, **event):
        data = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(BASE + "/api/v1/events", data=data, method="POST", headers={
            "Content-Type": "application/json", "Origin": BASE, "X-CSRF-Token": self.csrf})
        status, body = self._send(req)
        self.csrf = body.get("csrf_token", self.csrf)
        return body

    def wait_job(self, timeout=600):
        t0 = time.time()
        while time.time() - t0 < timeout:
            _, p = self.get("/api/v1/pending")
            if not p["pending"] or p["status"] in ("succeeded", "failed"):
                return p["status"], time.time() - t0
            time.sleep(1)
        raise TimeoutError("job ไม่จบภายในเวลาที่กำหนด")


def walk(view):
    out = []

    def go(n):
        out.append(n)
        for c in n.get("children", []):
            go(c)
    go(view["main"])
    go(view["sidebar"])
    return out


def has(view, **match):
    return any(all(n.get(k) == v for k, v in match.items()) for n in walk(view))


def text_of(view):
    return json.dumps(view, ensure_ascii=False)


def compose(*args):
    r = subprocess.run(COMPOSE + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} ล้ม: {r.stderr[-500:]}")
    return r.stdout


def wait_health(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(BASE + "/api/v1/health", timeout=5) as r:
                if json.loads(r.read())["status"] == "ok":
                    return time.time() - t0
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError("ระบบไม่กลับมา ok")


def psql(sql):
    """อ่าน/แก้ DB ของ compose บนเครื่องพัฒนาเท่านั้น (ผู้ใช้ tfp ผ่าน socket ใน container)"""
    return compose("exec", "-T", "db", "psql", "-U", "tfp", "-d", "tfp", "-tAc", sql).strip()


def clear_results():
    n = psql("WITH d AS (DELETE FROM results RETURNING 1) SELECT count(*) FROM d")
    say(f"ลบผลคำนวณที่เก็บไว้ {n} แถว (DB ทดสอบของ compose)")


def job_state(job_id):
    """สถานะ:จำนวนครั้งที่ทำ:ชนิด error ของงานหนึ่งงาน"""
    return psql("SELECT status || ':' || attempts || ':' || coalesce(error->>'type', '') "
                f"FROM jobs WHERE id = '{uuid.UUID(job_id)}'")


def kill_worker_during(client, kind):
    """ฆ่า worker ระหว่างงานชนิด kind ที่หน้ารออยู่ แล้วเปิด worker ใหม่ — คืน (id ของงาน, เวลาที่ฆ่า)

    งานที่หน้ารอจบแล้วให้ส่ง resume เพื่อให้หน้าสร้างงานถัดไปเหมือนหน้าเว็บจริง; ฆ่าเมื่อ DB มีงาน kind กำลังทำ
    แล้วยืนยันหลังฆ่าว่างานนั้นยังไม่จบ (r1 รอสถานะ running ของงานแรกอย่างเดียว แต่งาน ecm จบใน 0.09 วินาที
    ระหว่างการถาม 2 ครั้ง และไม่ได้ resume ต่อไปถึงงาน series จึงค้าง)"""
    t0 = time.time()
    while True:
        p = client.get("/api/v1/pending")[1]
        if not p["pending"] or p["status"] in ("succeeded", "failed"):
            say(f"งานที่หน้ารอจบแล้ว ({p['status']}) → ส่ง resume แบบหน้าเว็บ")
            if not client.post(resume=True)["pending"]:
                raise AssertionError(f"หน้าแสดงผลครบโดยไม่มีงาน {kind} ให้ฆ่า worker ระหว่างทำ")
            t0 = time.time()
        elif p["status"] == "running":
            running = psql(f"SELECT id FROM jobs WHERE status = 'running' AND kind = '{kind}'").split()
            if len(running) > 1:
                raise AssertionError(f"มีงาน {kind} สถานะ running {len(running)} งาน")
            if running:
                break
        elif time.time() - t0 > 60:
            raise TimeoutError(f"งานอยู่ในคิว ({p['status']}) เกิน 60 วินาที worker ไม่รับงาน")
        time.sleep(0.5)
    job_id, t_kill = running[0], time.time()
    compose("kill", "worker")
    state = job_state(job_id)
    check(state.startswith("running:"), f"ฆ่า worker ระหว่างงาน {kind} {job_id[:8]} (หลังฆ่า DB ยังเป็น {state})")
    compose("start", "worker")
    return job_id, t_kill


def hms(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone(datetime.timedelta(hours=7))).strftime("%H:%M:%S")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    say("ผ่าน: " + msg)


def main(name):
    out = REPO / "private" / "verification" / name
    if out.exists():
        sys.exit(f"มีผลชื่อ {name} อยู่แล้ว ไม่เขียนทับ")
    out.mkdir(parents=True)
    say(f"เริ่ม · health ok ใน {wait_health():.1f} วินาที")

    # 1) ดึงข้อมูลแบบผู้เยี่ยมชม
    c = Client()
    _, v = c.get("/api/v1/view")
    check(c.last_set_cookie and "HttpOnly" in c.last_set_cookie, "ได้ cookie session แบบ HttpOnly")
    c.post(trigger="pick_role_visitor")
    v = c.post(trigger="nav_top_fetch")
    check(v["pending"], "กดดึงข้อมูลแล้วหน้ารอ job")
    status, secs = c.wait_job()
    check(status == "succeeded", f"job ดึงข้อมูลสำเร็จใน worker container ({secs:.1f} วินาที)")
    v = c.post(resume=True)
    check(not v["pending"] and has(v, type="vega_lite_chart") and "ดึงข้อมูลล่าสุดเมื่อ" in text_of(v),
          "หน้าแสดงกราฟและเวลาดึงข้อมูลหลัง job เสร็จ")
    read_at = float(psql("SELECT result->>'read_at' FROM jobs WHERE kind = 'fetch' AND status = 'succeeded' "
                         "ORDER BY finished_at DESC LIMIT 1"))
    shown = re.search(r"ดึงข้อมูลล่าสุดเมื่อ (\d\d:\d\d:\d\d)", text_of(v)).group(1)
    check(shown in {hms(read_at), hms(read_at + 1)},
          f"เวลาที่แสดง {shown} = เวลาที่ worker อ่านชีตเสร็จ ไม่ใช่เวลาที่งานดึงทั้งหมดเสร็จ ({secs:.1f} วินาที)")
    horizon = [n for n in walk(v) if n.get("id") == "tfp_forecast_horizon"][0]["index"]
    v = c.post(values={"tfp_forecast_horizon": (horizon + 1) % 4})
    check(not v["pending"], "เปลี่ยนช่วงพยากรณ์อ่านผลเดิม ไม่สร้าง job")
    chosen = (horizon + 1) % 4
    # 4c8aa71: backtest คำนวณเมื่อกดปุ่ม "เริ่มการทดสอบย้อนหลัง" (ไม่ใช่ตอนดึงข้อมูล) — session นี้กดไว้ ข้อ 4 จึงต้องใช้งาน series
    check("btn_run_rolling_bt" in {n.get("id") for n in walk(v)}, "ก่อนกด หน้าแสดงปุ่มเริ่มการทดสอบย้อนหลัง")
    v = c.post(trigger="btn_run_rolling_bt")
    check(v["pending"], "กดปุ่มแล้วหน้ารองาน backtest")
    status, secs = c.wait_job()
    v = c.post(resume=True)
    check(status == "succeeded" and not v["pending"] and "จุดทดสอบ" in text_of(v),
          f"งาน backtest สำเร็จและหน้าแสดงผล MAPE ({secs:.1f} วินาที)")

    # Warm reads must reuse completed results without creating compute jobs.
    jobs_before = psql("SELECT count(*) FROM jobs")
    warm_ms = []
    for _ in range(5):
        started = time.perf_counter()
        _, warm = c.get("/api/v1/view")
        warm_ms.append(round((time.perf_counter() - started) * 1000, 2))
        check(not warm["pending"] and has(warm, type="vega_lite_chart"), "warm view is ready")
    check(psql("SELECT count(*) FROM jobs") == jobs_before, "warm reads created zero jobs")
    say("warm API reads (ms, 5 sequential requests): " + json.dumps(warm_ms))

    # 2) รีสตาร์ตทั้งระบบ
    t0 = time.time()
    compose("restart")
    say(f"docker compose restart เสร็จ ({time.time() - t0:.1f} วินาที) · health ok ใน {wait_health():.1f} วินาที")
    _, v = c.get("/api/v1/view")
    check(not c.last_set_cookie, "หลังรีสตาร์ต cookie เดิมยังใช้ได้ (ไม่ได้ session ใหม่)")
    check(has(v, type="vega_lite_chart") and
          [n for n in walk(v) if n.get("id") == "tfp_forecast_horizon"][0]["index"] == chosen,
          "หลังรีสตาร์ตข้อมูล ผล และค่าที่เลือกยังอยู่")
    v = c.post(values={"tfp_forecast_horizon": horizon})
    check(not v["pending"], "หลังรีสตาร์ต CSRF เดิมใช้ส่ง event ได้")

    # 3) worker หายระหว่างงานดึงข้อมูล (session ใหม่ ยังไม่มีข้อมูล → job แรกคือ fetch)
    clear_results()
    c2 = Client()
    c2.get("/api/v1/view")
    c2.post(trigger="pick_role_visitor")
    v = c2.post(trigger="nav_top_fetch")
    check(v["pending"], "session ใหม่กดดึงข้อมูล")
    fetch_job, _ = kill_worker_during(c2, "fetch")
    status, secs = c2.wait_job(timeout=300)
    check(status == "failed" and job_state(fetch_job) == "failed:1:WorkerLost",
          f"งานดึงข้อมูลที่ค้างถูกปิดเป็นล้มเหลวหลัง lease หมด ไม่ทำซ้ำเอง ({secs:.1f} วินาทีหลังฆ่า worker)")
    v = c2.post(resume=True)
    check("ดึงข้อมูลไม่สำเร็จ" in text_of(v) and "งานหยุดกลางคัน" in text_of(v),
          "หน้าแสดงข้อความดึงข้อมูลไม่สำเร็จในแถบเดิม")
    c2.post(trigger="nav_top_fetch")
    status, secs = c2.wait_job()
    v = c2.post(resume=True)
    check(status == "succeeded" and "ดึงข้อมูลล่าสุดเมื่อ" in text_of(v), f"กดดึงใหม่สำเร็จ ({secs:.1f} วินาที)")
    say("jobs ล่าสุด: " + psql("SELECT kind || ':' || status || ':' || attempts FROM jobs ORDER BY created_at DESC LIMIT 3"))

    # 4) worker หายระหว่างงานคำนวณที่หน้าเปิดแล้วต้องใช้ (session เดิมมีข้อมูลแล้ว ผลถูกลบ → หน้าสร้างงาน ecm/series)
    clear_results()
    _, v = c.get("/api/v1/view")
    check(v["pending"], "เปิดหน้าเดิมเมื่อไม่มีผลที่เก็บไว้ → หน้ารองานคำนวณ")
    series_job, t_kill = kill_worker_during(c, "series")
    status, secs = c.wait_job(timeout=600)
    check(status == "succeeded" and job_state(series_job) == "succeeded:2:",
          f"งานคำนวณกลับเข้าคิวและทำซ้ำจนสำเร็จในครั้งที่ 2 ({secs:.1f} วินาทีหลังฆ่า worker)")
    v = c.post(resume=True)
    while v["pending"]:                    # หน้าอาจต้องรองานคำนวณถัดไป
        c.wait_job()
        v = c.post(resume=True)
    check(has(v, type="vega_lite_chart"), "หน้าแสดงกราฟหลังงานที่ทำซ้ำเสร็จ")
    logs = compose("logs", "--no-color", "--since", str(int(t_kill)), "worker")
    check("คืนงานที่ lease หมด" in logs, "log ของ worker หลังฆ่าในข้อนี้บันทึกการคืนงานที่ lease หมด")
    (out / "report.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    say(f"สรุป: ผ่านทุกข้อ · ผลอยู่ที่ {out.relative_to(REPO)}/report.txt")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        main(sys.argv[1])
    except (AssertionError, TimeoutError, RuntimeError) as e:
        say(f"ไม่ผ่าน: {e}")
        out = REPO / "private" / "verification" / sys.argv[1]
        if out.exists():
            (out / "report.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
        sys.exit(1)
