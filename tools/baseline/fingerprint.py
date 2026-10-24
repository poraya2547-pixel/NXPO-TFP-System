"""แปลงผลลัพธ์ (DataFrame, Series, ตัวเลข, dict ฯลฯ) เป็นรูปแบบกลางที่เทียบได้แบบตรงทุกบิต

ตัวเลขทศนิยมเก็บเป็น float.hex() จึงเทียบได้ละเอียดถึงบิตสุดท้าย ค่า NaN/inf แยกเป็นสตริง
ใช้ทั้งกับ baseline ของระบบเดิม และตอนเทียบกับโค้ดใหม่ในขั้นถัดไป
"""
import hashlib
import json
import math

import numpy as np
import pandas as pd


def _scalar(v):
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        if math.isnan(f):
            return "nan"
        if math.isinf(f):
            return "inf" if f > 0 else "-inf"
        return f.hex()
    if v is pd.NA or v is pd.NaT:
        return "na"
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        return str(v)
    return str(v)


def canonical(obj):
    """คืนโครงสร้างที่ json.dumps ได้ และคงลำดับแถว/คอลัมน์ตามเดิม"""
    if isinstance(obj, pd.DataFrame):
        return {
            "__type__": "DataFrame",
            "columns": [_scalar(c) for c in obj.columns],
            "index": [_scalar(i) for i in obj.index],
            "dtypes": [str(t) for t in obj.dtypes],
            "values": [[canonical(v) for v in row] for row in obj.itertuples(index=False, name=None)],
        }
    if isinstance(obj, pd.Series):
        return {
            "__type__": "Series",
            "name": _scalar(obj.name),
            "index": [_scalar(i) for i in obj.index],
            "dtype": str(obj.dtype),
            "values": [canonical(v) for v in obj.tolist()],
        }
    if isinstance(obj, np.ndarray):
        return {"__type__": "ndarray", "shape": list(obj.shape), "values": [canonical(v) for v in obj.ravel().tolist()]}
    if isinstance(obj, dict):
        return {"__type__": "dict", "items": [[_scalar(k), canonical(v)] for k, v in obj.items()]}
    if isinstance(obj, (list, tuple)):
        return {"__type__": type(obj).__name__, "items": [canonical(v) for v in obj]}
    return _scalar(obj)


def dumps(obj) -> str:
    return json.dumps(canonical(obj), ensure_ascii=False, separators=(",", ":"))


def sha256(obj) -> str:
    return hashlib.sha256(dumps(obj).encode("utf-8")).hexdigest()


def sha256_canonical(canon) -> str:
    """hash ของโครงสร้างที่ผ่าน canonical() แล้ว (เช่นที่อ่านกลับจากไฟล์ JSON) ให้ตรงกับ sha256()"""
    return hashlib.sha256(json.dumps(canon, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
