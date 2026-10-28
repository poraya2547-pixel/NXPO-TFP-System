"""เรียก data_loader.load_data_gsheet() ของเดิม โดยให้อ่านค่าจาก snapshot แทนการต่อ Google Sheets

ใช้แทน Google Sheets จริงตอนทดสอบ (ไม่ต้องใช้คีย์ ไม่เรียกเครือข่าย) โค้ดแปลงค่าในชีต
ยังเป็นของเดิมทุกบรรทัด เปลี่ยนแค่ client ที่ส่งค่าเข้าไป
"""
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "private" / "baseline" / "sheets_raw.json"


class _FakeWorksheet:
    def __init__(self, values):
        self._values = values

    def get_all_values(self, *args, **kwargs):
        return copy.deepcopy(self._values)


class _FakeSpreadsheet:
    def __init__(self, tabs):
        self._tabs = tabs

    def worksheet(self, title):
        return _FakeWorksheet(self._tabs[title])


class _FakeClient:
    def __init__(self, tabs):
        self._tabs = tabs

    def open_by_key(self, key):
        return _FakeSpreadsheet(self._tabs)


def load_tabs(path=SNAPSHOT) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))["tabs"]


def load_df_from_snapshot(path=SNAPSHOT):
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import data_loader

    tabs = load_tabs(path)
    original = data_loader._get_client
    data_loader._get_client = lambda: _FakeClient(tabs)
    try:
        return data_loader.load_data_gsheet()
    finally:
        data_loader._get_client = original
