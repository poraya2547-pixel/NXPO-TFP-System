#!/bin/sh
# เก็บหน้าจอ 52 สถานะของแอปต้นฉบับ (e6aee03) ด้วย AppTest ใน image ที่ระบุ แบบปิด network
# workspace ส่งเข้าแบบอ่านอย่างเดียว คัดลอกเฉพาะไฟล์แอป รูป ฟอนต์ เครื่องมือ snapshot และ log ของ baseline
# ผลเก็บใน private/baseline/ui/<ชื่อ>/ (ห้ามทับ) ตั้งเป็นอ่านอย่างเดียว
#
#   sh tools/baseline/ui_in_image.sh tfp-runtime:arm64 <ชื่อชุดใหม่>
set -eu
IMAGE="$1"
NAME="$2"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$REPO/private/baseline/ui/$NAME"
LOGDIR="$REPO/private/verification/$NAME"
if [ -e "$DEST" ] || [ -e "$LOGDIR" ]; then
    echo "มีชุดชื่อ $NAME อยู่แล้ว ไม่เขียนทับ" >&2
    exit 1
fi
mkdir -p "$LOGDIR"
IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
echo "$IMAGE $IMAGE_ID" > "$LOGDIR/image.txt"
docker run --rm --network none -e TFP_RUNTIME_IMAGE="$IMAGE_ID" \
    -v "$REPO:/src:ro" -v "$LOGDIR:/out" "$IMAGE" sh -c '
        set -e
        mkdir -p /work/tools/baseline /work/private/baseline/logs /work/private/baseline/ui
        cp /src/TFP_App1.3.0.py /src/TFP.py /src/data_loader.py /src/*.png /work/
        cp -r /src/fonts /work/fonts
        for f in ui_capture stage replay fingerprint safe_io runtime_info; do cp "/src/tools/baseline/$f.py" /work/tools/baseline/; done
        cp /src/private/baseline/sheets_raw.json /work/private/baseline/
        cp /src/private/baseline/logs/fetch_log_baseline.csv /work/private/baseline/logs/
        cd /work
        PYTHONHASHSEED=0 python -B tools/baseline/ui_capture.py "$0" > /out/capture_stdout.txt 2> /out/capture_stderr.txt
        cp -r "/work/private/baseline/ui/$0" "/out/capture"' "$NAME"
mv "$LOGDIR/capture" "$DEST"
chmod 444 "$DEST"/*
chmod 555 "$DEST"
tail -1 "$LOGDIR/capture_stdout.txt"
echo "ผล: private/baseline/ui/$NAME"
