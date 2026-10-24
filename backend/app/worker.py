"""worker 1 process: ดึง job จาก Postgres ด้วย FOR UPDATE SKIP LOCKED แล้วทำ (แผน §10)

- claim: เปลี่ยนเป็น running พร้อม claim_token/lease แล้ว commit ทันที (ไม่ถือ lock ระหว่างคำนวณ)
- ระหว่างทำ: ต่อ lease ทุก LEASE/3 วินาที · บันทึกผลเฉพาะเมื่อ claim_token ยังเป็นของ worker นี้
- lease หมด (worker ตาย): งานคำนวณ (ecm/series) กลับเข้าคิวจนครบ max_attempts; งานอื่นถือว่าล้มเหลว
  (ดึงชีต/Gemini ไม่เรียกซ้ำอัตโนมัติ ผู้ใช้กดใหม่เอง)

    python -m app.worker
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid

from psycopg.types.json import Jsonb

from . import compute, config, db, jobs

log = logging.getLogger("tfp.worker")
LEASE_SECONDS = 60
POLL_SECONDS = 1.0
NAME = f"{socket.gethostname()}-{os.getpid()}"
_stop = threading.Event()


def reclaim_expired(url: str) -> int:
    with db.tx(url) as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = CASE WHEN dedupe_key IS NOT NULL AND attempts < max_attempts "
            "THEN 'queued' ELSE 'failed' END, "
            "error = CASE WHEN dedupe_key IS NOT NULL AND attempts < max_attempts THEN NULL "
            "ELSE %s END, claim_token = NULL, lease_until = NULL, "
            "finished_at = CASE WHEN dedupe_key IS NOT NULL AND attempts < max_attempts THEN NULL ELSE now() END "
            "WHERE status = 'running' AND lease_until < now()",
            (Jsonb({"type": "WorkerLost", "text": "งานหยุดกลางคัน (worker ไม่ตอบ) กรุณาลองใหม่"}),))
        return cur.rowcount


def claim(url: str):
    token = uuid.uuid4()
    with db.tx(url) as conn:
        row = conn.execute(
            "SELECT id, kind, params FROM jobs WHERE status = 'queued' AND run_after <= now() "
            "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE jobs SET status = 'running', claimed_by = %s, claim_token = %s, attempts = attempts + 1, "
                     "lease_until = now() + make_interval(secs => %s), started_at = now() WHERE id = %s",
                     (NAME, token, LEASE_SECONDS, row[0]))
    return {"id": row[0], "kind": row[1], "params": row[2], "token": token}


def _heartbeat(url: str, job: dict, done: threading.Event):
    while not done.wait(LEASE_SECONDS / 3):
        with db.tx(url) as conn:
            conn.execute("UPDATE jobs SET lease_until = now() + make_interval(secs => %s) "
                         "WHERE id = %s AND claim_token = %s", (LEASE_SECONDS, job["id"], job["token"]))
        beat(url)  # Long-running jobs must also keep worker health fresh.


def finish(url: str, job: dict, result=None, error=None) -> bool:
    with db.tx(url) as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = %s, result = %s, error = %s, finished_at = now(), lease_until = NULL "
            "WHERE id = %s AND claim_token = %s AND status = 'running'",
            ("failed" if error else "succeeded", Jsonb(result) if result is not None else None,
             Jsonb(error) if error else None, job["id"], job["token"]))
        return cur.rowcount == 1


def run_one(url: str) -> bool:
    job = claim(url)
    if job is None:
        return False
    done = threading.Event()
    hb = threading.Thread(target=_heartbeat, args=(url, job, done), daemon=True)
    hb.start()
    try:
        result = jobs.execute(db.PostgresStore(url), job["kind"], job["params"])
        ok = finish(url, job, result=result)
    except Exception as e:
        log.exception("job %s (%s) failed", job["id"], job["kind"])
        ok = finish(url, job, error=compute.error_record(e))
    finally:
        done.set()
        hb.join()
    if not ok:
        log.warning("job %s: lease หมดก่อนบันทึกผล ไม่ทับสถานะใหม่", job["id"])
    return True


def beat(url: str):
    with db.tx(url) as conn:
        conn.execute("INSERT INTO workers (name, seen_at) VALUES (%s, now()) "
                     "ON CONFLICT (name) DO UPDATE SET seen_at = now()", (NAME,))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = config.settings()
    db.migrate(s.database_url)
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    log.info("worker %s เริ่มทำงาน", NAME)
    last_maint = 0.0
    while not _stop.is_set():
        try:
            if time.monotonic() - last_maint > 30:
                beat(s.database_url)
                n = reclaim_expired(s.database_url)
                if n:
                    log.warning("คืนงานที่ lease หมด %d งาน", n)
                db.purge_expired(s.database_url, s.session_idle_minutes)
                last_maint = time.monotonic()
            if not run_one(s.database_url):
                _stop.wait(POLL_SECONDS)
        except Exception:
            log.exception("worker loop")
            _stop.wait(5)
    log.info("worker %s หยุด", NAME)


if __name__ == "__main__":
    main()
