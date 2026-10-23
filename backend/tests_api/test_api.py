"""สัญญา API, session/CSRF/สิทธิ์ และการทำงานร่วมกับ worker บน Postgres จริง (ค่าทดสอบทั้งหมด)"""
import json
import os
from pathlib import Path

from conftest import ORIGIN, find, nodes, post_event, run_jobs


def test_view_creates_session_cookie_and_landing(client):
    r = client.get("/api/v1/view")
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "tfp_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie  # host-only
    v = r.json()
    assert v["csrf_token"] and not v["pending"]
    assert find(v, type="button", id="pick_role_visitor") and find(v, type="button", id="toggle_research_login")
    assert r.headers["cache-control"] == "no-store"
    assert ";base64," not in r.text and "/api/v1/assets/" in r.text  # รูป/ฟอนต์ส่งเป็น URL ไม่ใช่ base64


def test_post_requires_allowed_origin_and_csrf(client):
    v = client.get("/api/v1/view").json()
    body = {"trigger": "pick_role_visitor"}
    assert client.post("/api/v1/events", json=body).status_code == 403
    assert client.post("/api/v1/events", json=body, headers={"Origin": "http://evil.example",
                                                               "X-CSRF-Token": v["csrf_token"]}).status_code == 403
    assert client.post("/api/v1/events", json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": "x"}).status_code == 403
    r = post_event(client, v["csrf_token"], **body)
    assert r.status_code == 200 and find(r.json(), type="button", id="nav_top_fetch")


def test_post_without_session_is_rejected(client):
    r = client.post("/api/v1/events", json={"trigger": "pick_role_visitor"},
                    headers={"Origin": ORIGIN, "X-CSRF-Token": "anything"})
    assert r.status_code == 403


def test_event_validation(client):
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    assert post_event(client, csrf, trigger="nav_logout").status_code == 400            # ปุ่มที่ไม่มีบนหน้า
    assert post_event(client, csrf, values={"tfp_forecast_horizon": 1}).status_code == 400  # ช่องที่ไม่มีบนหน้า
    assert post_event(client, csrf, trigger="x" * 500).status_code == 422
    assert post_event(client, csrf, values={"a": {"b": 1}}).status_code == 422
    big = json.dumps({"values": {"x": "y" * 70000}})
    r = client.post("/api/v1/events", content=big, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf,
                                                            "Content-Type": "application/json"})
    assert r.status_code == 413


def test_visitor_fetch_runs_as_job_then_shows_results(client, fresh_db):
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    v = post_event(client, csrf, trigger="pick_role_visitor").json()
    assert not find(v, type="vega_lite_chart")                   # ยังไม่มีข้อมูล
    v = post_event(client, csrf, trigger="nav_top_fetch").json()
    assert v["pending"] and find(v, type="spinner", text="กำลังดึงข้อมูลอัตโนมัติ...")
    assert client.get("/api/v1/pending").json() == {"pending": True, "status": "queued"}
    assert run_jobs(fresh_db) == 1
    assert client.get("/api/v1/pending").json() == {"pending": True, "status": "succeeded"}
    v = post_event(client, csrf, resume=True).json()
    assert not v["pending"]
    banner = [n for n in nodes(v) if n["type"] == "markdown" and "ดึงข้อมูลล่าสุดเมื่อ" in n["body"]]
    assert banner and find(v, type="vega_lite_chart") and find(v, type="selectbox", id="tfp_forecast_horizon")
    # บันทึกการดึงข้อมูลลงตาราง (เดิม fetch_log.csv)
    from app import db
    with db.tx(fresh_db) as conn:
        assert conn.execute('SELECT "user" FROM fetch_log').fetchall() == [("ผู้เยี่ยมชม",)]
    # เปลี่ยน horizon อ่านผลที่คำนวณไว้ ไม่สร้าง job ใหม่
    v = post_event(client, csrf, values={"tfp_forecast_horizon": 2}).json()
    assert not v["pending"] and run_jobs(fresh_db) == 0


def test_downloads_belong_to_their_session(client, fresh_db):
    from fastapi.testclient import TestClient

    from app.main import app

    csrf = client.get("/api/v1/view").json()["csrf_token"]
    post_event(client, csrf, trigger="pick_role_visitor")
    post_event(client, csrf, trigger="nav_top_fetch")
    run_jobs(fresh_db)
    v = post_event(client, csrf, resume=True).json()
    dl = find(v, type="download_button")[0]
    r = client.get(dl["url"])
    assert r.status_code == 200 and r.content and "attachment" in r.headers["content-disposition"]
    with TestClient(app, base_url=ORIGIN) as other:
        other.get("/api/v1/view")
        assert other.get(dl["url"]).status_code == 404


def _login(client, csrf, user, pw):
    v = client.get("/api/v1/view").json()
    submit = [n for n in nodes(v) if n["type"] == "button" and n.get("is_form_submitter")][0]
    u = [n for n in nodes(v) if n["type"] == "text_input" and n["label"].startswith("ชื่อผู้ใช้")][0]
    p = [n for n in nodes(v) if n["type"] == "text_input" and n["label"].startswith("รหัสผ่าน")][0]
    return post_event(client, csrf, trigger=submit["id"], values={u["id"]: user, p["id"]: pw})


def test_login_rotates_session_and_never_echoes_password(client):
    v = client.get("/api/v1/view").json()
    csrf = v["csrf_token"]
    old_cookie = client.cookies.get("tfp_session")
    post_event(client, csrf, trigger="toggle_research_login")
    r = _login(client, csrf, "wrong-user", "wrong-pass")
    assert r.status_code == 200 and find(r.json(), type="alert", kind="error", body="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    assert "wrong-pass" not in r.text
    r = _login(client, csrf, "test-user", "test-pass")
    assert r.status_code == 200 and "test-pass" not in r.text
    new = r.json()
    assert find(new, type="button", id="nav_logout")             # เข้าสู่ระบบแล้ว
    assert new["csrf_token"] != csrf and client.cookies.get("tfp_session") != old_cookie
    # token และ CSRF เดิมใช้ไม่ได้แล้ว
    assert post_event(client, csrf, trigger="nav_logout").status_code == 403
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app, base_url=ORIGIN, cookies={"tfp_session": old_cookie}) as stale_client:
        stale = stale_client.get("/api/v1/view")
        assert find(stale.json(), type="button", id="pick_role_visitor")  # session ใหม่ ไม่ใช่ของคณะวิจัย
        assert "tfp_session=" in stale.headers.get("set-cookie", "")  # ได้ session ใหม่แทน
    # ออกจากระบบ → token เปลี่ยนอีกครั้ง
    before = client.cookies.get("tfp_session")
    r = post_event(client, new["csrf_token"], trigger="nav_logout")
    assert r.status_code == 200 and client.cookies.get("tfp_session") != before


def test_login_attempts_are_limited(client):
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    post_event(client, csrf, trigger="toggle_research_login")
    for _ in range(5):
        assert _login(client, csrf, "test-user", "nope").status_code == 200
    r = _login(client, csrf, "test-user", "test-pass")
    assert r.status_code == 429  # ถูกระงับชั่วคราว แม้รหัสถูก


def test_research_pages_need_login(client):
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    v = post_event(client, csrf, trigger="pick_role_visitor").json()
    assert not find(v, type="button", id="nav_sec_1_data_admin")
    assert post_event(client, csrf, trigger="nav_sec_1_data_admin").status_code == 400
    v = post_event(client, csrf, trigger="nav_switch_to_research").json()   # กลับหน้าเลือกบทบาท
    v = post_event(client, csrf, trigger="toggle_research_login").json()
    v = post_event(client, csrf, trigger="nav_sec_1_data_admin").json()     # คณะวิจัยที่ยังไม่ล็อกอิน
    assert find(v, type="button", id="data_admin_goto_login")
    assert not find(v, type="text_input", id="custom_gsheet_url_input")


def test_fetch_error_text_is_escaped(client, fresh_db, monkeypatch):
    from app import jobs

    def boom(url=None):
        raise ValueError("<img src=x onerror=alert(1)> ไม่พบชีต")

    monkeypatch.setattr(jobs, "_load_data_gsheet_with_optional_url", boom)
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    post_event(client, csrf, trigger="pick_role_visitor")
    post_event(client, csrf, trigger="nav_top_fetch")
    run_jobs(fresh_db)
    v = post_event(client, csrf, resume=True).json()
    banner = [n for n in nodes(v) if n["type"] == "markdown" and "ดึงข้อมูลไม่สำเร็จ" in n["body"]]
    assert banner and "&lt;img src=x onerror=alert(1)&gt; ไม่พบชีต" in banner[0]["body"]
    assert "<img src=x" not in banner[0]["body"]


def test_health_reports_worker(client, fresh_db):
    r = client.get("/api/v1/health")
    assert r.json()["database"] is True and r.json()["status"] == "degraded"
    from app import worker
    worker.beat(fresh_db)
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_assets_served_immutable(client):
    v = client.get("/api/v1/view")
    import re
    url = re.search(r"/api/v1/assets/[0-9a-f]{64}", v.text).group(0)
    r = client.get(url)
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"] and r.content
    assert client.get("/api/v1/assets/" + "0" * 64).status_code == 404


def test_openapi_contract_exported(client):
    spec = client.get("/api/v1/openapi.json").json()
    contract = Path(__file__).resolve().parents[2] / "docs/contracts/openapi.json"
    assert spec == json.loads(contract.read_text(encoding="utf-8"))
    assert {"/api/v1/view", "/api/v1/events", "/api/v1/pending", "/api/v1/health"} <= set(spec["paths"])
    assert os.environ.get("TFP_SHEETS_FIXTURE")
