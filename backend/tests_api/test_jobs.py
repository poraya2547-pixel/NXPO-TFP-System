"""Step 5: คิวงานบน Postgres และ worker — งานซ้ำ, SKIP LOCKED, worker หาย/lease หมด, worker เก่าเขียนทับไม่ได้,
งานล้มเหลว, ผลแยกตามรุ่นโค้ด/runtime, session ไม่ปนกัน, ขีดจำกัดการดึงข้อมูล/คำขอ และ SQL แบบ parameterized
(ค่าทดสอบทั้งหมด ไม่ต่อ Google Sheets/Gemini)"""
import ast
import json
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
from conftest import ORIGIN, find, post_event, run_jobs

from app import db, jobs, version, worker

APP = Path(__file__).resolve().parents[1] / "app"
ECM = {"dataset_id": 1, "lr_vars": ["ln_FDI"], "sr_spec": [["d_ln_FDI", 1]]}


def _sid():
    return str(uuid.uuid4())


def _row(url, job_id):
    with db.tx(url) as conn:
        return conn.execute("SELECT status, attempts, result, error FROM jobs WHERE id = %s", (job_id,)).fetchone()


def _expire_lease(url, job_id):
    """จำลอง worker หยุดกลางคัน: lease ไม่ถูกต่อจนหมดเวลา"""
    with db.tx(url) as conn:
        conn.execute("UPDATE jobs SET lease_until = now() - interval '1 second' WHERE id = %s", (job_id,))


def test_same_compute_job_is_shared_until_finished(fresh_db, monkeypatch):
    store = db.PostgresStore(fresh_db)
    a = store.start_job(_sid(), "ecm", ECM)
    assert store.start_job(_sid(), "ecm", ECM) == a                 # input เดียวกัน (คนละ session) → งานเดียว
    other = store.start_job(_sid(), "ecm", {**ECM, "lr_vars": ["ln_TRADE"]})
    assert other != a
    monkeypatch.setattr(jobs, "execute", lambda store, kind, params: {})
    assert run_jobs(fresh_db) == 2
    assert store.start_job(_sid(), "ecm", ECM) != a                 # งานเดิมจบแล้ว สร้างงานใหม่ได้


def test_fetch_jobs_are_never_merged(fresh_db):
    store = db.PostgresStore(fresh_db)
    s = _sid()
    assert store.start_job(s, "fetch", {"url": None}) != store.start_job(s, "fetch", {"url": None})


def test_concurrent_duplicate_submits_create_one_job(fresh_db):
    store = db.PostgresStore(fresh_db)
    ids, gate = [], threading.Barrier(8)

    def submit():
        gate.wait()
        ids.append(store.start_job(_sid(), "series", {"dataset_id": 1}))

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ids) == 8 and len(set(ids)) == 1
    with db.tx(fresh_db) as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_two_workers_never_claim_the_same_job(fresh_db):
    store = db.PostgresStore(fresh_db)
    for _ in range(6):
        store.start_job(_sid(), "fetch", {"url": None})
    claimed, gate = [], threading.Barrier(6)

    def grab():
        gate.wait()
        job = worker.claim(fresh_db)
        if job:
            claimed.append(job["id"])

    threads = [threading.Thread(target=grab) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 6 and len(set(claimed)) == 6
    assert worker.claim(fresh_db) is None


def test_lost_compute_job_is_retried_then_failed(fresh_db):
    store = db.PostgresStore(fresh_db)
    job_id = store.start_job(_sid(), "series", {"dataset_id": 1})
    for attempt in (1, 2, 3):
        assert str(worker.claim(fresh_db)["id"]) == job_id
        _expire_lease(fresh_db, job_id)
        assert worker.reclaim_expired(fresh_db) == 1
        status, attempts, _, error = _row(fresh_db, job_id)
        assert attempts == attempt
        assert status == ("queued" if attempt < 3 else "failed")
    assert error["type"] == "WorkerLost"


def test_lost_fetch_job_fails_without_retry(fresh_db):
    store = db.PostgresStore(fresh_db)
    job_id = store.start_job(_sid(), "fetch", {"url": None})
    worker.claim(fresh_db)
    _expire_lease(fresh_db, job_id)
    assert worker.reclaim_expired(fresh_db) == 1
    status, attempts, _, error = _row(fresh_db, job_id)
    assert (status, attempts, error["type"]) == ("failed", 1, "WorkerLost")   # ดึงชีตไม่เรียกซ้ำเอง ผู้ใช้กดใหม่


def test_stale_worker_cannot_overwrite_new_owner(fresh_db):
    store = db.PostgresStore(fresh_db)
    job_id = store.start_job(_sid(), "series", {"dataset_id": 1})
    old = worker.claim(fresh_db)
    _expire_lease(fresh_db, job_id)
    worker.reclaim_expired(fresh_db)
    new = worker.claim(fresh_db)                                     # worker อื่นรับงานต่อ
    assert worker.finish(fresh_db, old, result={"by": "old"}) is False   # worker เดิมกลับมาช้า
    assert worker.finish(fresh_db, new, result={"by": "new"}) is True
    status, attempts, result, _ = _row(fresh_db, job_id)
    assert (status, attempts, result) == ("succeeded", 2, {"by": "new"})


def test_heartbeat_keeps_a_long_job_alive(fresh_db, monkeypatch):
    worker.beat(fresh_db)
    with db.tx(fresh_db) as conn:
        conn.execute("UPDATE workers SET seen_at = now() - interval '5 minutes'")
    monkeypatch.setattr(worker, "LEASE_SECONDS", 3)
    monkeypatch.setattr(jobs, "execute", lambda store, kind, params: time.sleep(5) or {"done": True})
    job_id = db.PostgresStore(fresh_db).start_job(_sid(), "series", {"dataset_id": 1})
    t = threading.Thread(target=worker.run_one, args=(fresh_db,))
    t.start()
    time.sleep(4)                                                    # นานกว่า lease เริ่มต้น
    try:
        assert worker.reclaim_expired(fresh_db) == 0
        from app.main import health
        assert health()["status"] == "ok", "busy worker must keep its health heartbeat fresh"
    finally:
        t.join()
    assert _row(fresh_db, job_id)[:3] == ("succeeded", 1, {"done": True})


def test_failed_job_keeps_type_and_message_only(fresh_db, monkeypatch):
    def broken(store, kind, params):
        raise ZeroDivisionError("หารด้วยศูนย์ในงานทดสอบ")

    monkeypatch.setattr(jobs, "execute", broken)
    job_id = db.PostgresStore(fresh_db).start_job(_sid(), "series", {"dataset_id": 1})
    assert run_jobs(fresh_db) == 1
    status, _, _, error = _row(fresh_db, job_id)
    assert status == "failed" and error == {"type": "ZeroDivisionError", "text": "หารด้วยศูนย์ในงานทดสอบ"}
    assert "Traceback" not in json.dumps(error)


def test_results_are_keyed_by_code_version_and_runtime(fresh_db, monkeypatch):
    store = db.PostgresStore(fresh_db)
    raw = pd.DataFrame({"Year": [2020, 2021], "TFP": [251.09, 252.6]})
    ds = store.add_dataset(raw)
    assert store.add_dataset(raw.copy()) == ds                       # เนื้อหาเดิม → dataset เดิม
    store.save_series(ds, {"value": 1.5})
    assert store.series(ds) == {"value": 1.5}
    monkeypatch.setattr(version, "runtime_fingerprint", lambda: "another-runtime")
    assert store.series(ds) is None                                  # ผลของ runtime อื่นไม่ถูกนำมาใช้
    monkeypatch.undo()
    monkeypatch.setattr(version, "code_version", lambda: "another-code")
    assert store.series(ds) is None                                  # ผลของโค้ดรุ่นอื่นไม่ถูกนำมาใช้


def _fetched_visitor(client, url):
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    post_event(client, csrf, trigger="pick_role_visitor")
    post_event(client, csrf, trigger="nav_top_fetch")
    run_jobs(url)
    return csrf, post_event(client, csrf, resume=True).json()


def test_sessions_do_not_share_choices(client, fresh_db):
    from fastapi.testclient import TestClient

    from app.main import app

    csrf_a, va = _fetched_visitor(client, fresh_db)
    with TestClient(app, base_url=ORIGIN) as other:
        _, vb = _fetched_visitor(other, fresh_db)
        before = find(vb, type="selectbox", id="tfp_forecast_horizon")[0]["index"]
        changed = post_event(client, csrf_a, values={"tfp_forecast_horizon": (before + 1) % 4}).json()
        assert find(changed, type="selectbox", id="tfp_forecast_horizon")[0]["index"] == (before + 1) % 4
        vb = other.get("/api/v1/view").json()
        assert find(vb, type="selectbox", id="tfp_forecast_horizon")[0]["index"] == before


def test_fetch_limit_per_hour(client, fresh_db, monkeypatch):
    monkeypatch.setenv("TFP_FETCH_PER_HOUR", "1")
    csrf, _ = _fetched_visitor(client, fresh_db)
    v = post_event(client, csrf, trigger="nav_top_fetch").json()
    assert not v["pending"] and run_jobs(fresh_db) == 0
    assert "ดึงข้อมูลบ่อยเกินกำหนดต่อชั่วโมง" in json.dumps(v, ensure_ascii=False)


def test_events_per_minute_limit(client, monkeypatch):
    if time.time() % 60 > 50:                                        # อย่าให้ test คร่อมนาที
        time.sleep(61 - time.time() % 60)
    monkeypatch.setenv("TFP_EVENTS_PER_MINUTE", "3")
    csrf = client.get("/api/v1/view").json()["csrf_token"]
    codes = [post_event(client, csrf).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def _sql_ok(arg) -> bool:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return True
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        return _sql_ok(arg.left) and _sql_ok(arg.right)
    return False


def test_sql_is_parameterized():
    """ทุก conn.execute() ใช้ข้อความ SQL คงที่ (ค่าส่งเป็นพารามิเตอร์) ยกเว้นไฟล์ migration ของระบบเอง
    (execute ของ object อื่น เช่น PageRun.execute หรือ jobs.execute ไม่ใช่ SQL)"""
    bad, checked = [], 0
    for path in sorted(APP.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute" \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "conn" and node.args:
                checked += 1
                if _sql_ok(node.args[0]):
                    continue
                is_migration = (path.name == "db.py" and isinstance(node.args[0], ast.Call)
                                and getattr(node.args[0].func, "attr", None) == "read_text")
                if not is_migration:
                    bad.append(f"{path.name}:{node.lineno}")
    assert checked > 20, checked          # ตัวกรองต้องเจอคำสั่ง SQL จริง (กัน test ผ่านเพราะไม่ได้ตรวจอะไร)
    assert not bad, bad
