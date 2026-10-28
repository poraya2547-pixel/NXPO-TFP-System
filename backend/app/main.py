"""FastAPI: หน้าเว็บ (element tree จากโค้ดหน้าเดิม), event ของผู้ใช้, สถานะ job, ไฟล์ดาวน์โหลด และ asset

ความปลอดภัย (แผน §20.3):
- session ฝั่ง server ใน Postgres, cookie HttpOnly/SameSite=Lax/Secure(ตั้งค่าได้) host-only, token สุ่ม เก็บเฉพาะ hash
- ทุก POST ต้องมี Origin ที่อนุญาต และ X-CSRF-Token ตรงกับ session; ขนาดคำขอจำกัด
- เปลี่ยน token เมื่อเข้าสู่ระบบ/ออกจากระบบ; จำกัดการลองรหัสผ่านต่อ session และต่อที่อยู่ IP; จำกัดจำนวน event ต่อนาที
- สิทธิ์ของแต่ละหน้า/การกระทำตัดสินโดยโค้ดหน้าเดิมฝั่ง server; ไฟล์ดาวน์โหลดอ่านได้เฉพาะ session เจ้าของ
- ไม่ส่ง traceback/ค่าลับให้ผู้ใช้ (บันทึก log พร้อมรหัสอ้างอิง)
"""
from __future__ import annotations

import contextlib
import hmac
import logging
import mimetypes
import time
import urllib.parse
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import config, db, page_runner, schemas
from .ui import EventError

log = logging.getLogger("tfp.api")
COOKIE = "tfp_session"
LOGIN_FORM = "research_login_form"  # ฟอร์มเข้าสู่ระบบในหน้าเดิม (TFP_App1.3.0.py:3963)

@contextlib.asynccontextmanager
async def _lifespan(_app):
    url = config.settings().database_url
    if url:
        applied = db.migrate(url)
        if applied:
            log.info("migration: %s", applied)
    yield


app = FastAPI(title="TFP API", version="1.0", docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json",
              lifespan=_lifespan)
ASSETS: dict = {}


def _load_assets():
    """asset ของหน้า (รูป/ฟอนต์ที่หน้าเดิมฝังเป็น base64) — เนื้อไฟล์เดียวกับใน image"""
    import hashlib

    for p in page_runner.ASSETS_DIR.rglob("*"):
        if p.is_file():
            raw = p.read_bytes()
            mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            ASSETS[hashlib.sha256(raw).hexdigest()] = (mime, raw)


_load_assets()


def S() -> config.Settings:
    return config.settings()


def _secrets() -> dict:
    try:
        return config.secrets()
    except (RuntimeError, FileNotFoundError):
        return {}


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    ref = uuid.uuid4().hex[:12]
    log.exception("unhandled ref=%s path=%s", ref, request.url.path)
    return JSONResponse({"detail": "เกิดข้อผิดพลาดในระบบ", "ref": ref}, status_code=500)


@app.middleware("http")
async def _limits_and_headers(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        n = request.headers.get("content-length")
        if n is None or not n.isdigit() or int(n) > S().max_body_bytes:
            return JSONResponse({"detail": "คำขอใหญ่เกินกำหนดหรือไม่ระบุขนาด"}, status_code=413)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/v1/assets/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def _client_ip(request: Request) -> str:
    if S().trust_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "-"


def _check_post(request: Request, sess: dict | None):
    origin = request.headers.get("origin")
    if not origin or origin not in S().allowed_origins:
        raise HTTPException(403, "ต้นทางของคำขอไม่ได้รับอนุญาต")
    token = request.headers.get("x-csrf-token", "")
    if sess is None or not hmac.compare_digest(token.encode(), sess["csrf_token"].encode()):
        raise HTTPException(403, "CSRF token ไม่ถูกต้อง กรุณาโหลดหน้าใหม่")


def _set_cookie(resp: Response, token: str):
    resp.set_cookie(COOKIE, token, httponly=True, secure=S().cookie_secure, samesite="lax", path="/")


def _prepare(tree: dict) -> dict:
    """เติม URL ดาวน์โหลด และแทน data URI ด้วย URL ของ asset"""
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "download_button":
                n = dict(n, url=f"/api/v1/downloads/{urllib.parse.quote(n['ref'])}")
            return {k: walk(v) for k, v in n.items()}
        if isinstance(n, list):
            return [walk(v) for v in n]
        return n
    return page_runner.externalize_assets(walk(tree), ASSETS)


def _view(tree: dict, sess: dict) -> dict:
    t = _prepare(tree)
    return schemas.View(main=t["main"], sidebar=t["sidebar"], page_config=t["page_config"],
                        pending=bool(sess["state"].get("pending")), csrf_token=sess["csrf_token"]).model_dump()


def _rate_ok(sess: dict) -> bool:
    now_min = int(time.time() // 60)
    r = sess["state"].get("rate") or {}
    if r.get("m") != now_min:
        r = {"m": now_min, "n": 0}
    r["n"] += 1
    sess["state"]["rate"] = r
    return r["n"] <= S().events_per_minute


def _authenticated(state: dict) -> bool:
    vals = state.get("values")
    if not vals:
        return False
    return bool(page_runner.codec.decode(vals).get("research_authenticated"))


def _run(sess: dict, event: dict | None, resume: bool) -> dict:
    store = db.PostgresStore(S().database_url)
    state = sess["state"]
    out = page_runner.run(store, sess["id"], state, event, _secrets(), resume=resume, limits=S())
    new_state = out["state"]
    old_pending = state.get("pending")
    if not resume and new_state["pending"] is None and old_pending and old_pending.get("trigger"):
        new_state["pending"] = old_pending  # ยังรอผลของปุ่มที่กดไว้ (เช่นดึงข้อมูล) อยู่
    new_state["rate"] = state.get("rate")
    sess["state"] = new_state
    return out["tree"]


@app.get("/api/v1/view", response_model=schemas.View)
def get_view(request: Request):
    with db.tx(S().database_url) as conn:
        token = request.cookies.get(COOKIE)
        sess = db.load_session_for_update(conn, token, S().session_idle_minutes)
        new_token = None
        if sess is None:
            new_token, sess = db.new_session(conn, S().session_max_hours)
        tree = _run(sess, None, resume=False)
        db.save_session(conn, sess)
        body = _view(tree, sess)
    resp = JSONResponse(body)
    if new_token:
        _set_cookie(resp, new_token)
    return resp


@app.post("/api/v1/events", response_model=schemas.View)
def post_event(request: Request, event: schemas.Event):
    s = S()
    with db.tx(s.database_url) as conn:
        sess = db.load_session_for_update(conn, request.cookies.get(COOKIE), s.session_idle_minutes)
        _check_post(request, sess)
        if not _rate_ok(sess):
            raise HTTPException(429, "ส่งคำขอถี่เกินไป กรุณารอสักครู่")
        meta = (sess["state"].get("widget_meta") or {}).get(event.trigger or "", {})
        is_login = meta.get("form") == LOGIN_FORM
        keys = [f"s:{sess['id']}", f"ip:{_client_ip(request)}"]
        if is_login and db.login_failures(conn, keys, s.login_window_minutes) >= s.login_max_failures:
            raise HTTPException(429, f"ลองเข้าสู่ระบบไม่สำเร็จหลายครั้ง กรุณารอ {s.login_window_minutes} นาทีแล้วลองใหม่")
        was_auth = _authenticated(sess["state"])
        ev = {"trigger": event.trigger, "values": event.values} if not event.resume else None
        try:
            tree = _run(sess, ev, resume=event.resume)
        except EventError as e:
            raise HTTPException(400, str(e))
        now_auth = _authenticated(sess["state"])
        new_token = None
        if now_auth != was_auth:
            new_token = db.rotate_session(conn, sess)
            db.PostgresStore(s.database_url).audit("login_ok" if now_auth else "logout", sess["id"])
        elif is_login and not now_auth:
            db.add_login_failure(conn, keys)
            db.PostgresStore(s.database_url).audit("login_failed", sess["id"])
        db.save_session(conn, sess)
        body = _view(tree, sess)
    resp = JSONResponse(body)
    if new_token:
        _set_cookie(resp, new_token)
    return resp


@app.get("/api/v1/pending", response_model=schemas.PendingStatus)
def get_pending(request: Request):
    with db.tx(S().database_url) as conn:
        sess = db.load_session_for_update(conn, request.cookies.get(COOKIE), S().session_idle_minutes)
        if sess is None or not sess["state"].get("pending"):
            return {"pending": False, "status": None}
        job = db.PostgresStore(S().database_url).job(sess["state"]["pending"]["job_id"])
        return {"pending": True, "status": job["status"]}


@app.get("/api/v1/downloads/{ref}")
def get_download(request: Request, ref: str):
    with db.tx(S().database_url) as conn:
        sess = db.load_session_for_update(conn, request.cookies.get(COOKIE), S().session_idle_minutes)
    if sess is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    row = db.PostgresStore(S().database_url).download(sess["id"], ref)
    if row is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    data, file_name, mime = row
    quoted = urllib.parse.quote(file_name)
    return Response(bytes(data), media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=\"download{Path(file_name).suffix}\"; filename*=UTF-8''{quoted}"})


@app.get("/api/v1/assets/{sha}")
def get_asset(sha: str):
    item = ASSETS.get(sha)
    if item is None:
        raise HTTPException(404, "ไม่พบไฟล์")
    mime, raw = item
    return Response(raw, media_type=mime, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/v1/health", response_model=schemas.Health)
def health():
    try:
        with db.tx(S().database_url) as conn:
            row = conn.execute("SELECT extract(epoch FROM now() - max(seen_at)) FROM workers").fetchone()
        seen = None if row[0] is None else float(row[0])
        ok = seen is not None and seen < 120
        return {"status": "ok" if ok else "degraded", "database": True, "worker_seen_seconds_ago": seen}
    except Exception:
        log.exception("health: database")
        return JSONResponse({"status": "degraded", "database": False, "worker_seen_seconds_ago": None},
                            status_code=503)
