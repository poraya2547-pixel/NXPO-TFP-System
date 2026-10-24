"""โหมดข้อมูลตัวอย่าง: ให้ปุ่มดึงข้อมูลอ่าน snapshot ของชีต (ไฟล์ JSON) แทน Google Sheets จริง

ใช้ตอนพัฒนา/ทดสอบ local และกับ IT ก่อนได้รับอนุญาตให้ต่อ Sheets — ตั้ง TFP_SHEETS_FIXTURE=<path ของ sheets_raw.json>
แทนเฉพาะ client ที่ loader ใช้อ่านค่า (แบบเดียวกับ tools/baseline/replay.py) โค้ดแปลงข้อมูลของ loader เดิมยังทำงานครบ
TFP_SHEETS_FIXTURE_DELAY=<วินาที> (เฉพาะทดสอบ): หน่วงก่อนอ่าน ให้ e2e ฆ่า worker ระหว่างงานดึงข้อมูลได้ (ตั้งแต่ 4c8aa71 งานดึงเหลือราว 1 วินาที)
"""
import contextlib
import copy
import json
import os
import time

from . import data_loader


class _Worksheet:
    def __init__(self, values):
        self._values = values

    def get_all_values(self, *args, **kwargs):
        return copy.deepcopy(self._values)


class _Spreadsheet:
    def __init__(self, tabs):
        self._tabs = tabs

    def worksheet(self, title):
        return _Worksheet(self._tabs[title])


class _Client:
    def __init__(self, tabs):
        self._tabs = tabs

    def open_by_key(self, key):
        return _Spreadsheet(self._tabs)


@contextlib.contextmanager
def maybe_fixture():
    path = os.environ.get("TFP_SHEETS_FIXTURE")
    if not path:
        yield False
        return
    with open(path, encoding="utf-8") as f:
        tabs = json.load(f)["tabs"]
    delay = float(os.environ.get("TFP_SHEETS_FIXTURE_DELAY") or 0)
    if delay > 0:
        time.sleep(delay)
    real = data_loader._get_client
    data_loader._get_client = lambda: _Client(tabs)
    try:
        yield True
    finally:
        data_loader._get_client = real
