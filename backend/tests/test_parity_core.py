"""เกณฑ์ A: โค้ดที่ย้ายใน backend/app ให้ผลตรงทุกบิตกับ oracle ของต้นฉบับ e6aee03 บน runtime เดียวกัน"""
import copy
import math
import sys
from pathlib import Path

import parity

APP_DIR = parity.REPO / "backend" / "app"


def failed_checks(cand, ref_dir):
    return [text for ok, text in parity.compare(cand, ref_dir) if not ok]


def test_candidate_matches_reference_bit_for_bit(computed, ref_dir):
    failed = failed_checks(parity.run_candidate(computed), ref_dir)
    assert not failed, "\n".join(failed)


def test_candidate_runs_moved_code_only(computed):
    for name, f in computed["code_files"].items():
        assert Path(f).resolve().is_relative_to(APP_DIR), (name, f)
    # ไม่ได้ใช้ TFP.py / data_loader.py ต้นฉบับ และไม่ต้องใช้ Streamlit
    originals = {"TFP", "data_loader", "streamlit"}
    assert not originals & set(computed["modules_loaded"])
    assert not originals & set(sys.modules)


def _bump_first_float(obj):
    """เลื่อนค่าทศนิยมตัวแรกที่พบไป 1 ulp (ค่าเก็บเป็น float.hex)"""
    if isinstance(obj, str) and obj.startswith(("0x", "-0x")):
        return math.nextafter(float.fromhex(obj), math.inf).hex(), True
    if isinstance(obj, dict):
        for k, v in obj.items():
            new, done = _bump_first_float(v)
            if done:
                obj[k] = new
                return obj, True
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            new, done = _bump_first_float(v)
            if done:
                obj[i] = new
                return obj, True
    return obj, False


def test_compare_rejects_any_change(computed, ref_dir):
    """ตัวเทียบต้องไม่ผ่านแบบว่างเปล่า: ต่าง 1 ulp, ผลขาด, runtime/seed/ธง/บันทึก fit ไม่ตรง ต้องตกทุกกรณี"""
    good = parity.run_candidate(computed)
    assert not failed_checks(good, ref_dir)

    def mutated(fn):
        cand = copy.deepcopy(good)
        fn(cand)
        return failed_checks(cand, ref_dir)

    for key in ("forecast.h5", "holdout", "rolling", "influence", "lr.params", "raw_df"):
        def bump(c, key=key):
            assert _bump_first_float(c["outputs"][key])[1], key
        assert any("เนื้อหาตรงทุกบิต" in t for t in mutated(bump)), key
    assert any("ผลครบ" in t for t in mutated(lambda c: c["outputs"].pop("influence")))
    assert any("runtime" in t for t in mutated(lambda c: c["runtime"].update(machine="x86_64")))
    assert any("PYTHONHASHSEED" in t for t in mutated(lambda c: c.update(hash_seed="1")))
    assert any("instrumentation_neutral" in t
               for t in mutated(lambda c: c["flags"].update(instrumentation_neutral=False)))
    assert any("บันทึก fit" in t
               for t in mutated(lambda c: c["fit_groups"]["holdout"][0].update(converged=None)))
