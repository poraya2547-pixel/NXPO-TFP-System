"""แปลงผลคำนวณ (DataFrame, Series, ตัวเลข numpy ฯลฯ) เป็น JSON และกลับมาเป็นวัตถุเดิมแบบไม่สูญเสีย

ใช้เก็บผลที่ worker คำนวณใน Postgres แล้วให้หน้าเว็บอ่านกลับมาใช้โดยไม่ fit โมเดลซ้ำ
- ทศนิยมเก็บเป็น float.hex จึงกลับมาได้ตรงทุกบิต (NaN/inf แยกเป็นชื่อ)
- เก็บชนิดข้อมูลของคอลัมน์และ index, ชื่อ index/คอลัมน์ และชนิดของ scalar numpy ไว้ด้วย
ตรวจด้วย backend/tests/test_codec.py (เข้ารหัสแล้วถอดกลับต้องได้ค่าเท่าเดิมทุกบิตและชนิดเดิม)
"""
import datetime
import math

import numpy as np
import pandas as pd

_NP_SCALARS = {"float64": np.float64, "float32": np.float32, "int64": np.int64, "int32": np.int32,
               "bool": np.bool_}


def _float(v: float):
    if math.isnan(v):
        return {"f": "nan"}
    if math.isinf(v):
        return {"f": "inf" if v > 0 else "-inf"}
    return {"f": v.hex()}


def _unfloat(d) -> float:
    s = d["f"]
    return float(s) if s in ("nan", "inf", "-inf") else float.fromhex(s)


def _index(idx: pd.Index):
    if isinstance(idx, pd.RangeIndex):
        return {"range": [idx.start, idx.stop, idx.step], "name": encode(idx.name)}
    return {"values": [encode(v) for v in idx.tolist()], "dtype": str(idx.dtype), "name": encode(idx.name)}


def _unindex(d) -> pd.Index:
    if "range" in d:
        return pd.RangeIndex(*d["range"], name=decode(d["name"]))
    return pd.Index([decode(v) for v in d["values"]], dtype=d["dtype"], name=decode(d["name"]))


def encode(obj):
    if obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, bool):
        return {"b": obj}
    if isinstance(obj, np.generic):
        name = obj.dtype.name
        if name not in _NP_SCALARS:
            raise TypeError(f"ไม่รองรับ numpy scalar ชนิด {name}")
        inner = obj.item()
        return {"np": name, "v": encode(inner)}
    if isinstance(obj, int):
        return {"i": str(obj)}
    if isinstance(obj, float):
        return _float(obj)
    if obj is pd.NA:
        return {"na": True}
    if isinstance(obj, datetime.datetime) and not isinstance(obj, pd.Timestamp):
        return {"dt": obj.isoformat()}
    if isinstance(obj, pd.DataFrame):
        return {"df": {
            "columns": _index(obj.columns),
            "index": _index(obj.index),
            "dtypes": [str(t) for t in obj.dtypes],
            "attrs": encode(obj.attrs),
            "data": [[encode(v) for v in obj.iloc[:, j].tolist()] for j in range(obj.shape[1])],
        }}
    if isinstance(obj, pd.Series):
        return {"s": {"name": encode(obj.name), "index": _index(obj.index), "dtype": str(obj.dtype),
                      "data": [encode(v) for v in obj.tolist()]}}
    if isinstance(obj, np.ndarray):
        return {"nd": {"dtype": str(obj.dtype), "shape": list(obj.shape),
                       "data": [encode(v) for v in obj.ravel().tolist()]}}
    if isinstance(obj, tuple):
        return {"t": [encode(v) for v in obj]}
    if isinstance(obj, list):
        return {"l": [encode(v) for v in obj]}
    if isinstance(obj, dict):
        return {"d": [[encode(k), encode(v)] for k, v in obj.items()]}
    raise TypeError(f"ไม่รองรับชนิด {type(obj).__name__}")


def decode(j):
    if j is None or isinstance(j, str):
        return j
    if not isinstance(j, dict) or len(j) == 0:
        raise ValueError("รูปแบบข้อมูลไม่ถูกต้อง")
    if "b" in j:
        return bool(j["b"])
    if "np" in j:
        return _NP_SCALARS[j["np"]](decode(j["v"]))
    if "i" in j:
        return int(j["i"])
    if "f" in j:
        return _unfloat(j)
    if "na" in j:
        return pd.NA
    if "dt" in j:
        return datetime.datetime.fromisoformat(j["dt"])
    if "df" in j:
        d = j["df"]
        cols = _unindex(d["columns"])
        df = pd.DataFrame({i: pd.Series([decode(v) for v in col], dtype=dt)
                           for i, (col, dt) in enumerate(zip(d["data"], d["dtypes"]))})
        if df.shape[1] == 0:
            df = pd.DataFrame(index=range(len(_unindex(d["index"]))))
        df.columns = cols
        df.index = _unindex(d["index"])
        df.attrs = decode(d["attrs"]) if "attrs" in d else {}
        return df
    if "s" in j:
        d = j["s"]
        return pd.Series([decode(v) for v in d["data"]], index=_unindex(d["index"]), dtype=d["dtype"],
                         name=decode(d["name"]))
    if "nd" in j:
        d = j["nd"]
        return np.array([decode(v) for v in d["data"]], dtype=d["dtype"]).reshape(d["shape"])
    if "t" in j:
        return tuple(decode(v) for v in j["t"])
    if "l" in j:
        return [decode(v) for v in j["l"]]
    if "d" in j:
        return {decode(k): decode(v) for k, v in j["d"]}
    raise ValueError("รูปแบบข้อมูลไม่ถูกต้อง")
