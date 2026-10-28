"""ตั้งค่ากลางของ test backend

- ต้องรันด้วย PYTHONHASHSEED=0 (ตาราง diagnostics ตัดสินเสมอด้วยลำดับของ set — TFP.py:427)
- import แพ็กเกจ app จาก backend/ และเครื่องมือ baseline จาก tools/baseline/ ผ่าน parity.py
- ผลคำนวณของโค้ดใหม่บน snapshot รันครั้งเดียวต่อรอบ test แล้วใช้ร่วมกันหลายไฟล์
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parity  # noqa: E402


def pytest_configure(config):
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise pytest.UsageError("ต้องรันด้วย PYTHONHASHSEED=0")


@pytest.fixture(scope="session")
def computed():
    return parity.compute()


@pytest.fixture(scope="session")
def ref_dir():
    d = parity.reference_set()
    assert d is not None, "runtime นี้ไม่มีชุด reference ที่ตรึงไว้ (docs/baseline/**/runtime.json) — เทียบไม่ได้"
    return d
