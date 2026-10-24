"""codec ต้องเข้ารหัสแล้วถอดกลับได้วัตถุเดิมทุกบิต รวมชนิดข้อมูล ชื่อ index และชนิด scalar"""
import datetime
import json

import numpy as np
import pandas as pd

import parity
from app import codec, compute
from app.modeling import tfp


def same(a, b):
    """เท่ากันทุกบิต และชนิดข้อมูล/ชื่อ index ตรงกัน (ลงไปถึงสมาชิกใน tuple/list/dict)"""
    assert type(a) is type(b), (type(a), type(b))
    if isinstance(a, pd.DataFrame):
        same(a.attrs, b.attrs)
        assert list(map(str, a.dtypes)) == list(map(str, b.dtypes))
        assert a.index.name == b.index.name and a.columns.name == b.columns.name
        assert type(a.index) is type(b.index) and str(a.index.dtype) == str(b.index.dtype)
        assert type(a.columns) is type(b.columns) and str(a.columns.dtype) == str(b.columns.dtype)
    elif isinstance(a, pd.Series):
        assert str(a.dtype) == str(b.dtype) and a.name == b.name and a.index.name == b.index.name
        assert type(a.index) is type(b.index) and str(a.index.dtype) == str(b.index.dtype)
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            same(x, y)
        return
    elif isinstance(a, dict):
        assert list(a) == list(b)
        for k in a:
            same(a[k], b[k])
        return
    assert parity.first_difference(parity.fingerprint.canonical(a), parity.fingerprint.canonical(b)) is None


def roundtrip(obj):
    return codec.decode(json.loads(json.dumps(codec.encode(obj))))


def test_roundtrip_oracle_outputs(computed):
    for key, obj in computed["outputs"].items():
        if hasattr(obj, "model"):  # ผล statsmodels ไม่เก็บ (หน้าเว็บใช้ผลที่สกัดแล้ว)
            continue
        same(obj, roundtrip(obj))


def test_roundtrip_ecm_bundle(computed):
    raw = computed["outputs"]["raw_df"]
    bundle = compute.ecm_bundle(raw, tfp.LONG_RUN_VARS, tfp.SHORT_RUN_SPEC)
    same(bundle, roundtrip(bundle))
    assert isinstance(roundtrip(bundle)["sr_spec"][0], tuple)


def test_roundtrip_scalars():
    values = [None, True, False, 0, -7, 10**30, 0.1, -0.0, float("nan"), float("inf"), float("-inf"), "ไทย",
              np.float64(1.5), np.int64(3), np.bool_(True), pd.NA, (1, "a"), [1, [2.5]],
              {"a": 1, 2: "b", ("x", 1): None}, datetime.datetime(2026, 9, 27, 23, 50, 9),
              pd.DataFrame({"a": [1, 2]}, index=pd.RangeIndex(5, 7, name="r")),
              pd.Series(["x", None], dtype="str", name="s"), np.array([[1.0, 2.0]])]
    for v in values:
        if v is pd.NA:
            assert roundtrip(v) is pd.NA
        else:
            same(v, roundtrip(v))
    assert str(roundtrip(-0.0)) == "-0.0"
