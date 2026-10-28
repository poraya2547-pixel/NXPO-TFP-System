#!/bin/sh
# เปิดเว็บ TFP บน Mac เครื่องนี้ แล้วเปิดลิงก์ ngrok ให้คนที่อยู่ในรายชื่ออีเมลเข้าได้ (ล็อกอิน Google)
#   sh tools/demo/start_review.sh            # Gemini จำลอง (ไม่ใช้โควตา)
#   sh tools/demo/start_review.sh --gemini   # Gemini จริง (คีย์ใน private/local/secrets.gemini.toml)
# รายชื่ออีเมล: private/local/ngrok-policy.review.json (ต้องเป็นตัวพิมพ์เล็ก) · ปิดด้วย tools/demo/stop_review.sh
# ข้อมูลยังเป็น snapshot (ไม่ใช่ Google Sheets จริง) · ต้องเปิด Mac/Docker ไว้ และห้ามให้เครื่องหลับระหว่างใช้
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
URL="https://qualify-spew-unkempt.ngrok-free.dev"
ENV_FILE=private/local/env.ngrok
[ "${1:-}" = "--gemini" ] && ENV_FILE=private/local/env.ngrok.gemini
[ -f "$ENV_FILE" ] || { echo "ไม่พบ $ENV_FILE" >&2; exit 1; }
[ -f private/local/ngrok-policy.review.json ] || { echo "ไม่พบรายชื่ออีเมล ngrok-policy.review.json" >&2; exit 1; }

open -a Docker
i=0; until docker info >/dev/null 2>&1; do i=$((i+1)); [ $i -gt 60 ] && { echo "Docker ไม่ขึ้น" >&2; exit 1; }; sleep 3; done
docker compose -p tfp --env-file "$ENV_FILE" -f deploy/compose.yaml up -d --no-build >/dev/null
i=0; until curl -s http://127.0.0.1:8090/api/v1/health | grep -q '"status":"ok"'; do
  i=$((i+1)); [ $i -gt 60 ] && { echo "เว็บไม่พร้อม (health)" >&2; exit 1; }; sleep 2; done
echo "เว็บพร้อมที่ http://127.0.0.1:8090 ($ENV_FILE)"

if pgrep -f "ngrok http 127.0.0.1:8090" >/dev/null; then
  echo "ngrok เปิดอยู่แล้ว"
else
  mkdir -p private/tunnel
  LOG="private/tunnel/ngrok-$(date +%Y%m%d-%H%M%S).log"
  nohup ngrok http 127.0.0.1:8090 --url "$URL" --traffic-policy-file private/local/ngrok-policy.review.json \
      --inspect=false --log=stdout --log-format=json > "$LOG" 2>&1 < /dev/null &
  sleep 8
fi
code=$(curl -s -o /dev/null -w "%{http_code}" "$URL/" || true)
if [ "$code" = "302" ]; then
  echo "ลิงก์พร้อม: $URL (เข้าด้วย Google ตามรายชื่ออีเมล)"
else
  echo "ลิงก์ยังไม่พร้อม (HTTP $code) ดู log ใน private/tunnel/" >&2; exit 1
fi
echo "ระหว่างใช้งาน: เปิดอีกหน้าต่าง Terminal แล้วรัน  caffeinate -dis  กันเครื่องหลับ (Ctrl+C เมื่อเลิก)"
