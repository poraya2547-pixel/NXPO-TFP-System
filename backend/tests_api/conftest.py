"""test ของ API (FastAPI + Postgres + worker) — รันใน image ของ backend คู่กับ Postgres ทดสอบ (deploy/compose.test.yaml)

ใช้ค่าทดสอบทั้งหมด: รหัสคณะวิจัย test-user/test-pass, คีย์ Gemini ปลอม, ชีตจาก snapshot (TFP_SHEETS_FIXTURE)
แต่ละ test ได้ฐานข้อมูลว่างใหม่ (ลบ schema แล้ว migrate) และทำ job ด้วย worker.run_one ในเธรดเดียวกัน
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TEST_SECRETS = 'GEMINI_API_KEY = "test-gemini-key"\nRESEARCH_USERNAME = "test-user"\nRESEARCH_PASSWORD = "test-pass"\n'
ORIGIN = "http://testserver"


@pytest.fixture(scope="session", autouse=True)
def _env(tmp_path_factory):
    if not os.environ.get("TFP_DATABASE_URL"):
        raise pytest.UsageError("ต้องตั้ง TFP_DATABASE_URL ของ Postgres ทดสอบ (ดู deploy/compose.test.yaml)")
    secrets_file = tmp_path_factory.mktemp("secrets") / "secrets.toml"
    secrets_file.write_text(TEST_SECRETS, encoding="utf-8")
    os.environ.update({"TFP_SECRETS_FILE": str(secrets_file), "TFP_COOKIE_SECURE": "0",
                       "TFP_ALLOWED_ORIGINS": ORIGIN, "TFP_LOGIN_MAX_FAILURES": "5"})
    if not os.environ.get("TFP_SHEETS_FIXTURE"):
        raise pytest.UsageError("ต้องตั้ง TFP_SHEETS_FIXTURE (snapshot ชีต) — test ห้ามต่อ Google Sheets จริง")


@pytest.fixture()
def fresh_db():
    from app import db

    url = os.environ["TFP_DATABASE_URL"]
    with db.tx(url) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    db.migrate(url)
    return url


@pytest.fixture()
def client(fresh_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url=ORIGIN) as c:
        yield c


def post_event(client, csrf, **body):
    return client.post("/api/v1/events", json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})


def nodes(view):
    out = []

    def walk(n):
        out.append(n)
        for c in n.get("children", []):
            walk(c)
    walk(view["main"])
    walk(view["sidebar"])
    return out


def find(view, **match):
    return [n for n in nodes(view) if all(n.get(k) == v for k, v in match.items())]


def run_jobs(url):
    from app import worker

    n = 0
    while worker.run_one(url):
        n += 1
    return n
