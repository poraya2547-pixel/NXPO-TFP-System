"""Step 5: การดึงชีตตามแผน §9A ด้วย snapshot (ไม่ต่อ Google Sheets จริง ไม่แก้ชีต)

- เวลา "ดึงข้อมูลล่าสุดเมื่อ" และประวัติการดึง = เวลาที่อ่านชีตสำเร็จ (ไม่ใช่เวลาที่หน้ารันต่อหลังคำนวณเสร็จ)
- ชุด B = ชุด A ที่แก้ค่าหนึ่งช่องของปีเดิม (ไฟล์ชั่วคราวของ test): ได้ dataset และผลใหม่ที่คำนวณจาก B;
  กดดึง A อีกครั้ง: อ่านชีตใหม่จริงแต่ใช้ dataset/ผลเดิม; แก้ชีตแต่ยังไม่กดดึง: หน้าใช้ข้อมูลที่อ่านไว้
- งานดึงที่กดก่อนแต่เสร็จทีหลังไม่ทับข้อมูลของการกดครั้งใหม่; ลิงก์ชีตของคณะวิจัยเป็นของ session นั้น
- ดึงไม่สำเร็จหลังเคยสำเร็จ (เช่นหมดเวลาเชื่อมต่อ): ข้อความเดิม ล้างข้อมูลแบบหน้าเดิม ไม่บันทึกประวัติการดึง
- ระบบใหม่มี worker ตัวเดียว: Sheets ที่ค้างต้องหมดเวลาเองไม่ขวางงานอื่น และคำขอดึงที่รอเกินเพดานถูกปฏิเสธโดยไม่สร้างงาน
"""
import datetime
import json
import os
import re
import socket
import threading
import time
from pathlib import Path

from conftest import ORIGIN, find, nodes, post_event, run_jobs

from app import codec, compute, data_loader, db, jobs, worker
from app.modeling import tfp

TH = datetime.timezone(datetime.timedelta(hours=7))
LINK = "https://docs.google.com/spreadsheets/d/TEST-SHEET-B/edit"


def _snapshot_b(tmp_path, year="2010", code="TFPI"):
    """ชุด B = snapshot เดิมที่แก้ค่า TFPI ของปีเดิมหนึ่งช่อง (ปีและจำนวนแถวเท่าเดิม)"""
    snap = json.loads(Path(os.environ["TFP_SHEETS_FIXTURE"]).read_text(encoding="utf-8"))
    data = snap["tabs"]["Data"]
    col = data[0].index(code)
    row = next(r for r in data if r[0] == year)
    row[col] = repr(float(row[col]) + 1.0)
    path = tmp_path / "sheets_b.json"
    path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _visitor(client):
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    post_event(client, csrf, trigger="pick_role_visitor")
    return csrf


def _fetch(client, csrf, url):
    assert post_event(client, csrf, trigger="nav_top_fetch").json()["pending"]
    run_jobs(url)
    return post_event(client, csrf, resume=True).json()


def _session_dataset(url, client):
    with db.tx(url) as conn:
        return conn.execute("SELECT state->'dataset_id' FROM sessions WHERE token_hash = %s",
                            (db._hash(client.cookies.get("tfp_session")),)).fetchone()[0]


def _fetch_jobs(url):
    with db.tx(url) as conn:
        return conn.execute("SELECT status, params, result FROM jobs WHERE kind = 'fetch' ORDER BY created_at").fetchall()


COUNT = {"results": "SELECT count(*) FROM results", "fetch_log": "SELECT count(*) FROM fetch_log"}


def _count(url, table):
    with db.tx(url) as conn:
        return conn.execute(COUNT[table]).fetchone()[0]


def _charts(view):
    return json.dumps([n["spec"] for n in nodes(view) if n["type"] == "vega_lite_chart"], sort_keys=True)


def _hms(t):
    return datetime.datetime.fromtimestamp(t, TH).strftime("%H:%M:%S")


def test_fetch_time_is_when_the_sheet_was_read(client, fresh_db, monkeypatch):
    real = jobs.ensure_default_results
    monkeypatch.setattr(jobs, "ensure_default_results", lambda store, ds: (real(store, ds), time.sleep(2.5)))
    csrf = _visitor(client)
    post_event(client, csrf, trigger="nav_top_fetch")
    run_jobs(fresh_db)
    resumed_at = time.time()
    v = post_event(client, csrf, resume=True).json()
    read_at = _fetch_jobs(fresh_db)[-1][2]["read_at"]
    assert resumed_at - read_at > 2.5                       # หน้ารันต่อหลังอ่านชีตเกิน 2.5 วินาที
    shown = re.findall(r"ดึงข้อมูลล่าสุดเมื่อ (\d\d:\d\d:\d\d)", json.dumps(v, ensure_ascii=False))
    assert shown and shown[0] in {_hms(read_at), _hms(read_at + 1)}
    with db.tx(fresh_db) as conn:
        (logged,) = conn.execute("SELECT timestamp FROM fetch_log").fetchone()
    minutes = {datetime.datetime.fromtimestamp(read_at + d, TH).strftime("%H:%M") for d in (0, 1)}
    assert re.search(r"เวลา (\d\d:\d\d) น\.$", logged).group(1) in minutes


def test_changed_cell_is_read_and_computed_again(client, fresh_db, monkeypatch, tmp_path):
    reads = []
    real_load = jobs._load_data_gsheet_with_optional_url
    monkeypatch.setattr(jobs, "_load_data_gsheet_with_optional_url",
                        lambda url=None: reads.append(url) or real_load(url))
    a, b = os.environ["TFP_SHEETS_FIXTURE"], _snapshot_b(tmp_path)
    csrf = _visitor(client)
    _fetch(client, csrf, fresh_db)
    ds_a = _session_dataset(fresh_db, client)
    # 4c8aa71: ดึงข้อมูลเตรียมแค่ ECM ค่าเริ่มต้น — backtest (series) คำนวณเมื่อกดปุ่ม "เริ่มการทดสอบย้อนหลัง"
    assert len(reads) == 1 and _count(fresh_db, "results") == 1

    monkeypatch.setenv("TFP_SHEETS_FIXTURE", b)            # ชีตถูกแก้แต่ยังไม่กดดึง
    va = post_event(client, csrf, values={"tfp_forecast_horizon": 2}).json()   # ช่วงพยากรณ์ 10 ปี ใช้กับทุกหน้าที่เทียบ
    assert not va["pending"] and run_jobs(fresh_db) == 0 and len(reads) == 1
    assert _session_dataset(fresh_db, client) == ds_a

    vb = _fetch(client, csrf, fresh_db)                    # กดดึงหลังแก้ค่าหนึ่งช่อง (ปีเท่าเดิม)
    ds_b = _session_dataset(fresh_db, client)
    assert len(reads) == 2 and ds_b != ds_a and _count(fresh_db, "results") == 2
    store = db.PostgresStore(fresh_db)
    raw_b = store.dataset(ds_b)
    lr, sr = list(tfp.LONG_RUN_VARS), list(tfp.SHORT_RUN_SPEC)
    assert codec.encode(store.ecm(ds_b, lr, sr)) == codec.encode(compute.ecm_bundle(raw_b, lr, sr))
    assert store.series(ds_b) is None and store.series(ds_a) is None    # ยังไม่มีใครกดปุ่ม backtest
    assert _charts(vb) != _charts(va)

    monkeypatch.setenv("TFP_SHEETS_FIXTURE", a)            # กดดึง A อีกครั้ง
    va2 = _fetch(client, csrf, fresh_db)
    assert len(reads) == 3                                 # อ่านชีตใหม่ทุกครั้งที่กด
    assert _session_dataset(fresh_db, client) == ds_a      # เนื้อหาเท่าเดิม → dataset เดิม
    assert _count(fresh_db, "results") == 2                # ใช้ผลที่คำนวณไว้ ไม่คำนวณซ้ำ
    assert _charts(va2) == _charts(va) and _count(fresh_db, "fetch_log") == 3
    # กดปุ่ม "เริ่มการทดสอบย้อนหลัง" → backtest ของข้อมูลชุดที่เปิดอยู่ (A) เท่านั้น
    assert post_event(client, csrf, trigger="btn_run_rolling_bt").json()["pending"]
    assert run_jobs(fresh_db) == 1
    assert not post_event(client, csrf, resume=True).json()["pending"]
    series_a = tfp.build_model_frame(store.dataset(ds_a))[tfp.DEP_VAR].dropna().sort_index()
    assert codec.encode(store.series(ds_a)["tfp_series"]) == codec.encode(series_a) and store.series(ds_b) is None
    assert _count(fresh_db, "results") == 3


def test_older_fetch_finishing_later_does_not_replace_newer(client, fresh_db, monkeypatch, tmp_path):
    a, b = os.environ["TFP_SHEETS_FIXTURE"], _snapshot_b(tmp_path)
    csrf = _visitor(client)
    post_event(client, csrf, trigger="nav_top_fetch")                 # กดครั้งแรก
    old = worker.claim(fresh_db)                                       # worker รับไปแล้วแต่ยังไม่เสร็จ
    assert post_event(client, csrf, trigger="nav_top_fetch").json()["pending"]   # กดอีกครั้งหลังชีตถูกแก้
    monkeypatch.setenv("TFP_SHEETS_FIXTURE", b)
    assert run_jobs(fresh_db) == 1                                     # งานที่สองเสร็จก่อน
    v = post_event(client, csrf, resume=True).json()
    ds_new = _session_dataset(fresh_db, client)
    monkeypatch.setenv("TFP_SHEETS_FIXTURE", a)
    store = db.PostgresStore(fresh_db)
    assert worker.finish(fresh_db, old, result=jobs.execute(store, old["kind"], old["params"]))  # งานแรกเสร็จทีหลัง
    ds_old = _fetch_jobs(fresh_db)[0][2]["dataset_id"]
    assert ds_old != ds_new
    assert client.get("/api/v1/pending").json() == {"pending": False, "status": None}
    after = client.get("/api/v1/view").json()
    assert _session_dataset(fresh_db, client) == ds_new and _charts(after) == _charts(v)


def _research(client):
    v = client.get("/api/v1/view").json()
    csrf = v["csrf_token"]
    v = post_event(client, csrf, trigger="toggle_research_login").json()
    submit = [n for n in nodes(v) if n["type"] == "button" and n.get("is_form_submitter")][0]
    user = [n for n in nodes(v) if n["type"] == "text_input" and n["label"].startswith("ชื่อผู้ใช้")][0]
    pw = [n for n in nodes(v) if n["type"] == "text_input" and n["label"].startswith("รหัสผ่าน")][0]
    v = post_event(client, csrf, trigger=submit["id"], values={user["id"]: "test-user", pw["id"]: "test-pass"}).json()
    assert find(v, type="button", id="nav_logout")
    return v["csrf_token"]


def test_custom_sheet_link_belongs_to_its_session(client, fresh_db, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    a, b = os.environ["TFP_SHEETS_FIXTURE"], _snapshot_b(tmp_path)
    csrf = _research(client)
    post_event(client, csrf, trigger="nav_sec_1_data_admin")
    v = post_event(client, csrf, trigger="data_admin_fetch_btn", values={"custom_gsheet_url_input": LINK}).json()
    assert v["pending"]
    with TestClient(app, base_url=ORIGIN) as other:                    # ผู้เยี่ยมชมอีก session กดดึงช่วงเดียวกัน
        csrf_o = _visitor(other)
        assert post_event(other, csrf_o, trigger="nav_top_fetch").json()["pending"]
        assert [p["url"] for _, p, _ in _fetch_jobs(fresh_db)] == [LINK, None]
        monkeypatch.setenv("TFP_SHEETS_FIXTURE", b)                    # ชีตตามลิงก์ของคณะวิจัย
        assert worker.run_one(fresh_db)
        monkeypatch.setenv("TFP_SHEETS_FIXTURE", a)                    # ชีตเริ่มต้น
        assert worker.run_one(fresh_db)
        vr = post_event(client, csrf, resume=True).json()
        assert post_event(other, csrf_o, resume=True).status_code == 200
        # หน้าจัดการข้อมูลเรียก st.rerun() ใน try/except Exception หลังดึงสำเร็จ (TFP_App1.3.0.py:6662) ข้อมูลต้องอยู่ต่อ
        assert "ดึงข้อมูลล่าสุดเมื่อ" in json.dumps(vr, ensure_ascii=False)
        ds_r, ds_o = _session_dataset(fresh_db, client), _session_dataset(fresh_db, other)
        assert [r["dataset_id"] for _, _, r in _fetch_jobs(fresh_db)] == [ds_r, ds_o] and ds_r != ds_o


def test_failed_fetch_after_success_clears_data_like_original(client, fresh_db, monkeypatch):
    csrf = _visitor(client)
    v = _fetch(client, csrf, fresh_db)
    assert find(v, type="vega_lite_chart")

    def timeout(url=None):
        raise TimeoutError("หมดเวลาเชื่อมต่อ Google Sheets")

    monkeypatch.setattr(jobs, "_load_data_gsheet_with_optional_url", timeout)
    v = _fetch(client, csrf, fresh_db)
    text = json.dumps(v, ensure_ascii=False)
    assert "ดึงข้อมูลไม่สำเร็จ: หมดเวลาเชื่อมต่อ Google Sheets" in text and "ดึงข้อมูลล่าสุดเมื่อ" not in text
    assert not find(v, type="vega_lite_chart")                 # หน้าเดิมลบข้อมูลชุดเก่าเมื่อดึงไม่สำเร็จ (:3232)
    assert _session_dataset(fresh_db, client) is None
    assert _count(fresh_db, "fetch_log") == 1                   # ไม่บันทึกการดึงที่ไม่สำเร็จ


def test_pending_fetch_cap_rejects_without_creating_a_job(client, fresh_db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("TFP_MAX_PENDING_FETCH", "1")
    csrf = _visitor(client)
    assert post_event(client, csrf, trigger="nav_top_fetch").json()["pending"]   # งานแรกยังรออยู่ในคิว
    with TestClient(app, base_url=ORIGIN) as other:
        csrf_o = _visitor(other)
        v = post_event(other, csrf_o, trigger="nav_top_fetch").json()
        assert not v["pending"] and len(_fetch_jobs(fresh_db)) == 1
        assert "ดึงข้อมูลไม่สำเร็จ: มีคำขอดึงข้อมูลรออยู่มากเกินกำหนด" in json.dumps(v, ensure_ascii=False)
        run_jobs(fresh_db)                                                # คิวว่างแล้วกดใหม่ได้
        assert _fetch(other, csrf_o, fresh_db) and len(_fetch_jobs(fresh_db)) == 2


def test_hanging_sheet_times_out_instead_of_blocking_the_worker(client, fresh_db, monkeypatch):
    """ชีตไม่ตอบ (จำลองด้วย proxy ในเครื่องที่รับการเชื่อมต่อแล้วเงียบ) → งานล้มเหลวเมื่อครบ timeout ไม่ค้างตลอดไป"""
    import gspread
    from google.auth.credentials import AnonymousCredentials

    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(8)
    held = []
    threading.Thread(target=lambda: [held.append(silent.accept()) for _ in range(8)], daemon=True).start()
    monkeypatch.delenv("TFP_SHEETS_FIXTURE")
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{silent.getsockname()[1]}")
    monkeypatch.setenv("TFP_SHEETS_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr(data_loader, "_get_client", lambda: gspread.authorize(AnonymousCredentials()))
    csrf = _visitor(client)
    post_event(client, csrf, trigger="nav_top_fetch")
    t0 = time.time()
    runner = threading.Thread(target=run_jobs, args=(fresh_db,), daemon=True)
    runner.start()
    runner.join(timeout=60)
    assert not runner.is_alive(), "งานดึงชีตค้างเกิน 60 วินาที"
    status, _, _ = _fetch_jobs(fresh_db)[0]
    with db.tx(fresh_db) as conn:
        (error,) = conn.execute("SELECT error FROM jobs WHERE kind = 'fetch'").fetchone()
    assert status == "failed" and error["type"] == "ReadTimeout" and time.time() - t0 < 20
    v = post_event(client, csrf, resume=True).json()
    assert "ดึงข้อมูลไม่สำเร็จ:" in json.dumps(v, ensure_ascii=False) and not find(v, type="vega_lite_chart")
    silent.close()
