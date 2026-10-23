#!/bin/sh
# ปิดลิงก์ ngrok และคืน API/worker เป็นค่า local (รับเฉพาะ http://127.0.0.1:8090, Gemini จำลอง) — ข้อมูลใน DB ไม่หาย
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
pkill -f "ngrok http 127.0.0.1:8090" 2>/dev/null && echo "ปิด ngrok แล้ว" || echo "ngrok ไม่ได้เปิดอยู่"
if docker info >/dev/null 2>&1; then
  docker compose -p tfp --env-file private/local/env -f deploy/compose.yaml up -d --no-deps --no-build api worker >/dev/null
  echo "API/worker กลับเป็นค่า local แล้ว (เว็บยังเปิดที่ http://127.0.0.1:8090 — ปิด Docker Desktop ได้ถ้าไม่ใช้)"
fi
