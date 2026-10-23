"""โหมดทดสอบของ Gemini: job summary ใช้คำตอบจากไฟล์แทนการเรียก Gemini จริง (ไม่มีคำขอออกอินเทอร์เน็ต ไม่มีค่าใช้จ่าย)

ใช้กับการพัฒนา/ทดสอบ local และ test เท่านั้น — ตั้ง TFP_GEMINI_FIXTURE=<path ของไฟล์ JSON>; ระบบที่ใช้งานจริงต้องไม่ตั้งค่านี้
(แบบเดียวกับ TFP_SHEETS_FIXTURE ของ sheets_fixture.py) ข้อความในไฟล์ต้องระบุชัดว่าเป็นคำตอบสังเคราะห์หรือบันทึกไว้ ไม่ใช่ผลสด

รูปแบบไฟล์: {"note": "...", "responses": [{"text": "..."} | {"error": {"code": 429, "response_json": {...}}}, ...]}
คำขอครั้งที่ n (นับต่อ process) ใช้ responses[n % จำนวน] — error สร้างเป็น google.genai.errors.ClientError (4xx) /
ServerError (5xx) ของ SDK จริง จึงได้ชนิดและข้อความแบบเดียวกับ error จริง; คำขอทุกครั้งบันทึกใน CALLS ให้ test ตรวจ
"""
import json
import os

from google.genai import errors

CALLS: list = []  # (model, contents, system_instruction) ของทุกคำขอใน process นี้


class _Response:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, responses):
        self._responses = responses

    def generate_content(self, *, model, contents, config=None):
        CALLS.append({"model": model, "contents": contents,
                      "system_instruction": getattr(config, "system_instruction", None)})
        r = self._responses[(len(CALLS) - 1) % len(self._responses)]
        if "error" in r:
            code = r["error"]["code"]
            raise (errors.ServerError if code >= 500 else errors.ClientError)(code, r["error"]["response_json"])
        return _Response(r["text"])


class FixtureClient:
    def __init__(self, responses):
        if not responses:
            raise ValueError("ไฟล์คำตอบของโหมดทดสอบ Gemini ไม่มี responses")
        self.models = _Models(responses)


def load(path) -> FixtureClient:
    with open(path, encoding="utf-8") as f:
        return FixtureClient(json.load(f)["responses"])


def client(real_factory):
    """client ที่ job summary ใช้: ไฟล์ของโหมดทดสอบถ้าตั้ง TFP_GEMINI_FIXTURE ไม่งั้นสร้าง client จริงด้วย real_factory()"""
    path = os.environ.get("TFP_GEMINI_FIXTURE")
    return load(path) if path else real_factory()
