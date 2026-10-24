"""รันแอปเดิมโดยให้ปุ่มดึงข้อมูลอ่านจาก snapshot แทน Google Sheets (ใช้ถ่ายภาพ baseline)

ไม่แก้ไฟล์แอป: แทนเฉพาะ data_loader._get_client ด้วย client ที่คืนค่าจาก snapshot แล้วรันไฟล์แอปเดิม
ผ่านโฟลเดอร์ทดสอบ (stage.py) ปุ่มดึงข้อมูลจึงเขียน fetch_log.csv ลง log ของโฟลเดอร์นั้น ไม่ปนกับ workspace
การล็อกอินคณะวิจัยใช้ .streamlit/secrets.toml ใน cwd ผู้ใช้เป็นคนกรอกรหัสเอง

    cd ~/Developer/TFP_system_refactor_from_repo_20261009
    STAGE=$(/opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/stage.py <ชื่อใหม่>)
    TFP_STAGE="$STAGE" PYTHONHASHSEED=0 /opt/anaconda3/envs/idntwww/bin/python -m streamlit run \\
        tools/baseline/run_app_snapshot.py --server.address 127.0.0.1 --server.port 8502 \\
        --server.headless true --browser.gatherUsageStats false
"""
import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(REPO), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import stage  # noqa: E402

STAGE = Path(os.environ.get("TFP_STAGE", ""))
if not os.environ.get("TFP_STAGE") or not (STAGE / stage.APP_FILE).is_symlink():
    raise RuntimeError("ต้องตั้ง TFP_STAGE เป็นโฟลเดอร์ที่สร้างด้วย stage.py เพื่อไม่ให้เขียน fetch_log.csv ของ workspace")

import data_loader  # noqa: E402
import replay  # noqa: E402

_TABS = replay.load_tabs()
data_loader._get_client = lambda: replay._FakeClient(_TABS)
runpy.run_path(str(STAGE / stage.APP_FILE), run_name="__main__")
