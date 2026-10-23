"""ค่าตั้งของ backend อ่านจาก environment — ไม่มีค่าลับในโค้ด

ระบบเดิมอ่านค่าลับจาก st.secrets (.streamlit/secrets.toml) ระบบใหม่อ่านไฟล์รูปแบบเดียวกันจาก path ที่กำหนด
ผู้ติดตั้งส่งไฟล์เดิมเข้า container แบบอ่านอย่างเดียว ไม่ต้องคัดลอกหรือสร้างคีย์ใหม่

- TFP_SECRETS_FILE      path ของไฟล์ TOML (ตาราง [gcp_service_account], GEMINI_API_KEY, RESEARCH_USERNAME/PASSWORD)
- TFP_CREDENTIALS_FILE  path ของ credentials.json (ทางสำรองแบบเดิม) ค่าเริ่มต้น credentials.json ใน cwd
- TFP_DATABASE_URL      การเชื่อมต่อ Postgres (รหัสผ่าน DB มาจาก IT/ไฟล์ .env ที่ไม่ขึ้น git)
- ค่าอื่นดู Settings ด้านล่าง (ค่าเริ่มต้นใช้กับเครื่องจริงที่มี HTTPS — local ตั้ง TFP_COOKIE_SECURE=0)
"""
import os
import tomllib
from dataclasses import dataclass


def secrets() -> dict:
    path = os.environ.get("TFP_SECRETS_FILE")
    if not path:
        raise RuntimeError("ไม่ได้ตั้ง TFP_SECRETS_FILE (ไฟล์ค่าลับรูปแบบเดียวกับ .streamlit/secrets.toml)")
    with open(path, "rb") as f:
        return tomllib.load(f)


def credentials_file() -> str:
    return os.environ.get("TFP_CREDENTIALS_FILE", "credentials.json")


def _int(name, default):
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    database_url: str
    cookie_secure: bool
    allowed_origins: tuple
    session_idle_minutes: int
    session_max_hours: int
    login_max_failures: int
    login_window_minutes: int
    events_per_minute: int
    fetch_per_hour: int
    max_pending_fetch: int     # งานดึงข้อมูลที่รอ/กำลังทำพร้อมกันได้ทั้งระบบ (worker มีตัวเดียว)
    sheets_timeout_seconds: float  # timeout ต่อคำขอ HTTP ไป Google Sheets ของงานดึงข้อมูล
    trust_proxy: bool          # เชื่อ X-Forwarded-For จาก reverse proxy ของระบบเท่านั้น
    max_body_bytes: int


def settings() -> Settings:
    return Settings(
        database_url=os.environ.get("TFP_DATABASE_URL", ""),
        cookie_secure=os.environ.get("TFP_COOKIE_SECURE", "1") != "0",
        allowed_origins=tuple(o.strip() for o in os.environ.get("TFP_ALLOWED_ORIGINS", "").split(",") if o.strip()),
        session_idle_minutes=_int("TFP_SESSION_IDLE_MINUTES", 240),
        session_max_hours=_int("TFP_SESSION_MAX_HOURS", 24),
        login_max_failures=_int("TFP_LOGIN_MAX_FAILURES", 5),
        login_window_minutes=_int("TFP_LOGIN_WINDOW_MINUTES", 15),
        events_per_minute=_int("TFP_EVENTS_PER_MINUTE", 120),
        fetch_per_hour=_int("TFP_FETCH_PER_HOUR", 20),
        max_pending_fetch=_int("TFP_MAX_PENDING_FETCH", 30),
        sheets_timeout_seconds=float(os.environ.get("TFP_SHEETS_TIMEOUT_SECONDS", 60)),
        trust_proxy=os.environ.get("TFP_TRUST_PROXY", "0") == "1",
        max_body_bytes=_int("TFP_MAX_BODY_BYTES", 65536),
    )
