"""สูตรผลกระทบสมมติฐานนโยบาย (scenario) ลอกจากโค้ดหน้าเว็บเดิม TFP_App1.3.0.py (repo เพื่อน commit e6aee03)

ในต้นฉบับไม่ได้เป็นฟังก์ชัน แต่เขียนซ้ำ inline สองที่ด้วยสูตรเดียวกัน:
หน้าพยากรณ์ 5109 (is_log) และ 5187 / 5201 / 5214 (pct_effect 3 แบบ) กับแดชบอร์ดนำเสนอ 5830-5837
ห้ามแก้สูตร ตรวจด้วย backend/tests/test_scenario.py
"""
import math

from .core import _PCT_SCALED_VARS


def scenario_pct_effect(var: str, coef: float, shock: float) -> float:
    """ผลกระทบต่อ TFP (%) เมื่อสมมติตัวแปรในสมการระยะยาวเปลี่ยนไป shock หน่วยตามชนิดตัวแปร"""
    if var.startswith("ln_"):
        return coef * shock
    elif var in _PCT_SCALED_VARS:
        return (math.exp(coef * shock / 100) - 1) * 100
    else:
        return (math.exp(coef * shock) - 1) * 100
