#!/bin/sh
# รัน oracle ของโค้ดต้นฉบับ (e6aee03) ใน image ที่ระบุ แบบปิด network
# workspace ส่งเข้าแบบอ่านอย่างเดียว คัดลอกเฉพาะไฟล์ต้นฉบับ เครื่องมือ oracle และ snapshot ไปโฟลเดอร์ชั่วคราวใน container
# ผลเก็บใน private/verification/<ชื่อ>/ (ห้ามทับ) แล้วคัดลอกผล oracle ไป private/baseline/ แบบอ่านอย่างเดียว
#
#   sh tools/baseline/oracle_in_image.sh tfp-runtime:arm64 <ชื่อผลใหม่>
set -eu
IMAGE="$1"
NAME="$2"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUTDIR="$REPO/private/verification/$NAME"
RESULT="$REPO/private/baseline/oracle_$NAME.json"
if [ -e "$OUTDIR" ] || [ -e "$RESULT" ]; then
    echo "มีผลชื่อ $NAME อยู่แล้ว ไม่เขียนทับ" >&2
    exit 1
fi
mkdir -p "$OUTDIR"
IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
echo "$IMAGE $IMAGE_ID" > "$OUTDIR/image.txt"
docker run --rm --network none -e TFP_RUNTIME_IMAGE="$IMAGE_ID" \
    -v "$REPO:/src:ro" -v "$OUTDIR:/out" "$IMAGE" sh -c '
        set -e
        mkdir -p /work/tools/baseline /work/private/baseline
        cp /src/TFP_App1.3.0.py /src/TFP.py /src/data_loader.py /work/
        for f in oracle replay fingerprint safe_io runtime_info; do cp "/src/tools/baseline/$f.py" /work/tools/baseline/; done
        cp /src/private/baseline/sheets_raw.json /work/private/baseline/
        cd /work
        python -B tools/baseline/oracle.py "$0" > /out/oracle_stdout.txt 2> /out/oracle_stderr.txt
        cp "/work/private/baseline/oracle_$0.json" /out/' "$NAME"
cp "$OUTDIR/oracle_$NAME.json" "$RESULT"
chmod 444 "$RESULT"
echo "ผล: private/baseline/oracle_$NAME.json"
