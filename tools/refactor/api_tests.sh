#!/bin/sh
# รัน test ของ API กับ Postgres ทดสอบ (deploy/compose.test.yaml) — ผลใน private/verification/<ชื่อ>/ (ห้ามทับ)
# รหัสผ่าน DB สุ่มใหม่ทุกครั้ง ใช้เฉพาะ container ทดสอบที่ถูกลบหลังจบ
#
#   sh tools/refactor/api_tests.sh <image ID ของ backend runtime> <ชื่อผลใหม่>
set -eu
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUTDIR="$REPO/private/verification/$2"
if [ -e "$OUTDIR" ]; then echo "มีผลชื่อ $2 อยู่แล้ว ไม่เขียนทับ" >&2; exit 1; fi
mkdir -p "$OUTDIR"
export TFP_RUNTIME_IMAGE="$1" TFP_TEST_OUT="$OUTDIR"
TFP_TEST_DB_PASSWORD="$(od -An -N18 -tx1 /dev/urandom | tr -d ' \n')"
export TFP_TEST_DB_PASSWORD
echo "$1" > "$OUTDIR/image.txt"
docker compose -f "$REPO/deploy/compose.test.yaml" up --abort-on-container-exit --exit-code-from tests tests > "$OUTDIR/compose.log" 2>&1 || true
docker compose -f "$REPO/deploy/compose.test.yaml" down -v > /dev/null 2>&1 || true
echo "pytest exit=$(cat "$OUTDIR/pytest_api.exit" 2>/dev/null || echo ไม่มีผล) · ผล: private/verification/$2/"

# Missing results or failed tests must fail the runner, even when compose returned zero.
test "$(cat "$OUTDIR/pytest_api.exit")" = 0
