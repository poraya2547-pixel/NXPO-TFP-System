"""Postgres: migration, ที่เก็บข้อมูล/ผล/job/ไฟล์ (interface เดียวกับ store_memory.MemoryStore) และ session

ทุกคำสั่งใช้ parameterized SQL (psycopg) ไม่ประกอบ SQL จากค่าที่ผู้ใช้ส่งมา
"""
from __future__ import annotations

import hashlib
import json
import secrets as pysecrets
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from . import codec, compute, version

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=False)


@contextmanager
def tx(url: str):
    with connect(url) as conn:
        with conn.transaction():
            yield conn


def migrate(url: str) -> list:
    """ใช้ไฟล์ migrations/NNN_*.sql ที่ยังไม่เคยใช้ ตามลำดับ (lock กันสอง process ทำพร้อมกัน)"""
    applied = []
    with tx(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(735001)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, "
                     "applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name not in done:
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
                applied.append(f.name)
    return applied


def _options_key(lr_vars, sr_spec) -> str:
    return json.dumps([list(lr_vars), [list(s) for s in sr_spec]], ensure_ascii=False)


def dedupe_key(kind: str, params: dict) -> str | None:
    """งานคำนวณที่ input เดียวกันใช้ job เดียว (ดึงชีต/Gemini/รายงานเป็นของแต่ละครั้งที่กด จึงไม่รวม)"""
    if kind not in ("ecm", "series"):
        return None
    return f"{kind}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}"


class PostgresStore:
    """ที่เก็บของหน้าเว็บและ worker — แต่ละ method เปิด transaction สั้นของตัวเอง"""

    def __init__(self, url: str):
        self.url = url

    # ----- dataset -----
    def add_dataset(self, raw, source=None) -> int:
        data = codec.encode(raw)
        h = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        with tx(self.url) as conn:
            row = conn.execute(
                "INSERT INTO datasets (content_sha256, data, source) VALUES (%s, %s, %s) "
                "ON CONFLICT (content_sha256) DO UPDATE SET content_sha256 = EXCLUDED.content_sha256 RETURNING id",
                (h, Jsonb(data), Jsonb(source or {}))).fetchone()
        return row[0]

    def dataset(self, dataset_id):
        with tx(self.url) as conn:
            row = conn.execute("SELECT data FROM datasets WHERE id = %s", (dataset_id,)).fetchone()
        if row is None:
            raise KeyError(f"ไม่พบ dataset {dataset_id}")
        return codec.decode(row[0])

    # ----- ผลคำนวณ (key รวมรุ่นโค้ดและ runtime) -----
    def _result(self, dataset_id, kind, options_key):
        with tx(self.url) as conn:
            row = conn.execute(
                "SELECT payload FROM results WHERE dataset_id = %s AND kind = %s AND options_key = %s "
                "AND code_version = %s AND runtime_fingerprint = %s",
                (dataset_id, kind, options_key, version.code_version(), version.runtime_fingerprint())).fetchone()
        return None if row is None else compute.unpack(row[0])

    def _save_result(self, dataset_id, kind, options_key, bundle):
        with tx(self.url) as conn:
            conn.execute(
                "INSERT INTO results (dataset_id, kind, options_key, code_version, runtime_fingerprint, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (dataset_id, kind, options_key, version.code_version(), version.runtime_fingerprint(),
                 Jsonb(compute.pack(bundle))))

    def ecm(self, dataset_id, lr_vars, sr_spec):
        return self._result(dataset_id, "ecm", _options_key(lr_vars, sr_spec))

    def save_ecm(self, dataset_id, lr_vars, sr_spec, bundle):
        self._save_result(dataset_id, "ecm", _options_key(lr_vars, sr_spec), bundle)

    def series(self, dataset_id):
        return self._result(dataset_id, "series", "")

    def save_series(self, dataset_id, bundle):
        self._save_result(dataset_id, "series", "", bundle)

    # ----- job -----
    def start_job(self, session_id, kind, params) -> str:
        key = dedupe_key(kind, params)
        with tx(self.url) as conn:
            if key:
                row = conn.execute("SELECT id FROM jobs WHERE dedupe_key = %s AND status IN ('queued', 'running')",
                                   (key,)).fetchone()
                if row:
                    return str(row[0])
            job_id = uuid.uuid4()
            conn.execute(
                "INSERT INTO jobs (id, session_id, kind, params, dedupe_key, status, max_attempts) "
                "VALUES (%s, %s, %s, %s, %s, 'queued', %s) ON CONFLICT DO NOTHING",
                (job_id, session_id, kind, Jsonb(params), key, 3 if key else 1))
            if key:  # มีงานเดียวกันถูกสร้างพร้อมกัน ใช้ตัวที่อยู่ในคิว
                row = conn.execute("SELECT id FROM jobs WHERE dedupe_key = %s AND status IN ('queued', 'running')",
                                   (key,)).fetchone()
                if row:
                    return str(row[0])
        return str(job_id)

    def job(self, job_id):
        with tx(self.url) as conn:
            row = conn.execute("SELECT status, result, error FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if row is None:
            raise KeyError("ไม่พบ job")
        return {"status": row[0], "result": row[1], "error": row[2]}

    def count_jobs(self, session_id, kind, minutes: int) -> int:
        with tx(self.url) as conn:
            return conn.execute("SELECT count(*) FROM jobs WHERE session_id = %s AND kind = %s "
                                "AND created_at > now() - make_interval(mins => %s)",
                                (session_id, kind, minutes)).fetchone()[0]

    def count_pending(self, kind) -> int:
        with tx(self.url) as conn:
            return conn.execute("SELECT count(*) FROM jobs WHERE kind = %s AND status IN ('queued', 'running')",
                                (kind,)).fetchone()[0]

    # ----- บันทึกการดึงข้อมูล / ไฟล์ดาวน์โหลด -----
    def fetch_log_append(self, row: dict):
        with tx(self.url) as conn:
            conn.execute('INSERT INTO fetch_log (timestamp, "user") VALUES (%s, %s)', (row["timestamp"], row["user"]))

    def fetch_log_rows(self):
        with tx(self.url) as conn:
            rows = conn.execute('SELECT timestamp, "user" FROM (SELECT id, timestamp, "user" FROM fetch_log '
                                'ORDER BY id DESC LIMIT 1000) t ORDER BY id').fetchall()
        return [{"timestamp": t, "user": u} for t, u in rows]

    def put_download(self, session_id, data: bytes, file_name: str, mime: str) -> str:
        sha = hashlib.sha256(data).hexdigest()
        with tx(self.url) as conn:
            row = conn.execute(
                "INSERT INTO downloads (ref, session_id, sha256, file_name, mime, data) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (session_id, sha256, file_name, mime) DO UPDATE SET created_at = now() RETURNING ref",
                (pysecrets.token_urlsafe(24), session_id, sha, file_name, mime, data)).fetchone()
        return row[0]

    def download(self, session_id, ref):
        with tx(self.url) as conn:
            row = conn.execute("SELECT data, file_name, mime FROM downloads WHERE ref = %s AND session_id = %s",
                               (ref, session_id)).fetchone()
        return row

    # ----- audit -----
    def audit(self, event: str, session_id=None, **detail):
        with tx(self.url) as conn:
            conn.execute("INSERT INTO audit (event, session_ref, detail) VALUES (%s, %s, %s)",
                         (event, str(session_id)[:8] if session_id else None, Jsonb(detail)))


# ===================== session =====================
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(conn, max_hours: int) -> tuple[str, dict]:
    token = pysecrets.token_urlsafe(32)
    sid = uuid.uuid4()
    csrf = pysecrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (id, token_hash, csrf_token, expires_at) "
                 "VALUES (%s, %s, %s, now() + make_interval(hours => %s))", (sid, _hash(token), csrf, max_hours))
    return token, {"id": str(sid), "csrf_token": csrf, "state": {}}


def load_session_for_update(conn, token: str | None, idle_minutes: int):
    """session ที่ยังไม่หมดอายุ (ล็อกแถวไว้ทั้งคำขอ — คำขอของ session เดียวกันจึงทำทีละคำขอ เหมือน Streamlit)"""
    if not token:
        return None
    row = conn.execute(
        "SELECT id, csrf_token, state FROM sessions WHERE token_hash = %s AND expires_at > now() "
        "AND last_seen > now() - make_interval(mins => %s) FOR UPDATE",
        (_hash(token), idle_minutes)).fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "csrf_token": row[1], "state": row[2]}


def save_session(conn, sess: dict):
    conn.execute("UPDATE sessions SET state = %s, last_seen = now() WHERE id = %s", (Jsonb(sess["state"]), sess["id"]))


def rotate_session(conn, sess: dict) -> str:
    """ออก token และ CSRF ใหม่หลังเปลี่ยนสิทธิ์ (ล็อกอิน/ออกจากระบบ) — token เดิมใช้ไม่ได้ทันที"""
    token = pysecrets.token_urlsafe(32)
    sess["csrf_token"] = pysecrets.token_urlsafe(32)
    conn.execute("UPDATE sessions SET token_hash = %s, csrf_token = %s WHERE id = %s",
                 (_hash(token), sess["csrf_token"], sess["id"]))
    return token


def login_failures(conn, keys: list, window_minutes: int) -> int:
    """จำนวนครั้งที่ผิดสูงสุดในช่วงเวลา ของ key ใด key หนึ่ง (session หรือที่อยู่ IP)"""
    rows = conn.execute("SELECT key, count(*) FROM login_failures WHERE key = ANY(%s) "
                        "AND at > now() - make_interval(mins => %s) GROUP BY key", (keys, window_minutes)).fetchall()
    return max((n for _, n in rows), default=0)


def add_login_failure(conn, keys: list):
    for k in keys:
        conn.execute("INSERT INTO login_failures (key) VALUES (%s)", (k,))


def purge_expired(url: str, idle_minutes: int) -> None:
    with tx(url) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < now() OR last_seen < now() - make_interval(mins => %s)",
                     (idle_minutes,))
        conn.execute("DELETE FROM downloads WHERE created_at < now() - interval '2 days'")
        conn.execute("DELETE FROM login_failures WHERE at < now() - interval '1 day'")
