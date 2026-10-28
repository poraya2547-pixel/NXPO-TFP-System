#!/bin/sh
# รัน test ของ backend และ parity CLI ของโค้ดใหม่ใน image ที่ระบุ แบบปิด network (ใช้เทียบเกณฑ์ A บน runtime Linux)
# workspace ส่งเข้าแบบอ่านอย่างเดียว ผลเก็บใน private/verification/<ชื่อ>/ (ห้ามทับ)
# ไม่ตั้งตัวแปร BLAS/OpenMP เพิ่ม (runtime identity ต้องตรงกับตอนตรึง reference)
#
#   sh tools/refactor/test_in_image.sh <image ID เต็ม เช่น sha256:37424b8d...> <ชื่อผลใหม่>
# ระบุ image ด้วย ID (Docker Desktop 29.4.1 ที่ใช้ containerd store บางครั้ง inspect ด้วยชื่อ tag ไม่เจอ)
set -eu
IMAGE="$1"
NAME="$2"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUTDIR="$REPO/private/verification/$NAME"
if [ -e "$OUTDIR" ]; then
    echo "มีผลชื่อ $NAME อยู่แล้ว ไม่เขียนทับ" >&2
    exit 1
fi
mkdir -p "$OUTDIR"
IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
echo "$IMAGE $IMAGE_ID" > "$OUTDIR/image.txt"
docker run --rm --network none -e PYTHONHASHSEED=0 -e TFP_RUNTIME_IMAGE="$IMAGE_ID" \
    -v "$REPO:/src:ro" -v "$OUTDIR:/out" -w /src "$IMAGE" sh -c '
        python -B -P -m pytest -p no:cacheprovider -v backend/tests > /out/pytest_backend.txt 2>&1
        echo $? > /out/pytest_backend.exit
        python -B -P backend/tests/parity.py "$0" /out > /out/parity_cli.txt 2>&1
        echo $? > /out/parity_cli.exit' "$NAME"
echo "pytest exit=$(cat "$OUTDIR/pytest_backend.exit") · parity exit=$(cat "$OUTDIR/parity_cli.exit") · ผล: private/verification/$NAME/"

# Propagate suite failures to callers; a printed failure must not exit successfully.
test "$(cat "$OUTDIR/pytest_backend.exit")" = 0
test "$(cat "$OUTDIR/parity_cli.exit")" = 0
