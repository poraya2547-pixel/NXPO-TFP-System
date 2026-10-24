"""โฟลเดอร์ทดสอบให้แอปเดิมเขียน fetch_log.csv ลง log แยก ไม่ปนกับ log ของ workspace

ไฟล์แอป (TFP_App1.3.0.py) กำหนดฟอนต์ รูป โลโก้ และ FETCH_LOG_PATH จากโฟลเดอร์ของตัวไฟล์
ด้วย os.path.abspath ซึ่งไม่ตาม symlink (TFP_App1.3.0.py:121-122, 1753) จึงรันผ่าน symlink
ของไฟล์แอปในโฟลเดอร์นี้ โดยฟอนต์และรูป .png ที่ root ชี้ของเดิม ส่วน fetch_log.csv
เป็นสำเนาของ log ตอนเก็บ baseline (private/baseline/logs/fetch_log_baseline.csv)

สร้างโฟลเดอร์สำหรับรันแอปถ่ายภาพ (ชื่อต้องไม่ซ้ำ):
    /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/stage.py <ชื่อ>
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
APP_FILE = "TFP_App1.3.0.py"
BASELINE_LOG = REPO / "private" / "baseline" / "logs" / "fetch_log_baseline.csv"
STAGES = REPO / "private" / "baseline" / "ui" / "stages"


def make_stage(stage_dir) -> Path:
    stage = Path(stage_dir)
    stage.mkdir(parents=True)  # ห้ามใช้โฟลเดอร์เดิมซ้ำ ไม่อย่างนั้น log จะปนกับรอบก่อน
    for name in [APP_FILE, "fonts", *sorted(p.name for p in REPO.glob("*.png"))]:
        (stage / name).symlink_to(REPO / name)
    shutil.copyfile(BASELINE_LOG, stage / "fetch_log.csv")
    return stage


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    import safe_io

    if len(sys.argv) != 2:
        sys.exit("ใช้: stage.py <ชื่อ>")
    try:
        print(make_stage(STAGES / safe_io.check_name(sys.argv[1])))
    except (FileExistsError, ValueError) as e:
        sys.exit(f"หยุด: {e}")
