"""ตัวตนของ runtime ที่มีผลต่อการคำนวณ ใช้ผูก reference กับ runtime ที่สร้างมัน

reference ของแต่ละ runtime ใช้เทียบได้เฉพาะเมื่อ identity ตรงกันทุกช่อง:
เครื่อง/สถาปัตยกรรม, build ของ Python, libc, เวอร์ชันและไฟล์ของ package ตัวเลข (hash ของ RECORD),
การตั้งค่า BLAS/LAPACK ที่ numpy/scipy รายงาน และตัวแปร env ที่มีผลต่อการคำนวณ
image ID ที่ผู้รันประกาศผ่าน TFP_RUNTIME_IMAGE เก็บไว้เป็นหลักฐานแต่ไม่ใช้เทียบ
(image ที่ส่งมอบสร้างต่อจาก stage runtime จึงมี ID ต่างแม้ layer ของ runtime เหมือนกัน)
"""
import contextlib
import hashlib
import importlib.metadata
import io
import os
import platform
import sys

NUMERIC = ["numpy", "pandas", "scipy", "statsmodels", "patsy"]
COMPUTE_ENV = ["PYTHONHASHSEED", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
               "VECLIB_MAXIMUM_THREADS", "OPENBLAS_CORETYPE"]
NOT_COMPARED = ["declared_image"]


def _record_sha(dist: str):
    text = importlib.metadata.distribution(dist).read_text("RECORD")
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def _blas_lapack(module) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        cfg = module.show_config(mode="dicts")
    deps = cfg.get("Build Dependencies", {})
    return {k: deps.get(k) for k in ("blas", "lapack")}


def runtime_identity() -> dict:
    import numpy
    import scipy

    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python_build": sys.version,
        "libc": list(platform.libc_ver()),
        "packages": {p: importlib.metadata.version(p) for p in NUMERIC},
        "package_record_sha256": {p: _record_sha(p) for p in NUMERIC},
        "blas_lapack": {"numpy": _blas_lapack(numpy), "scipy": _blas_lapack(scipy)},
        "compute_env": {k: os.environ.get(k) for k in COMPUTE_ENV},
        "declared_image": os.environ.get("TFP_RUNTIME_IMAGE"),
    }


def comparable(identity: dict) -> dict:
    return {k: v for k, v in identity.items() if k not in NOT_COMPARED}


if __name__ == "__main__":
    import json

    print(json.dumps(runtime_identity(), ensure_ascii=False, indent=1))
