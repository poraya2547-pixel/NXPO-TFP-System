"""รุ่นของโค้ดคำนวณและ runtime — ใช้เป็นส่วนหนึ่งของ key ของผลที่เก็บ (แผน §10)

ผลที่คำนวณด้วยโค้ดหรือ runtime อื่นจะไม่ถูกนำมาใช้ซ้ำ (เช่น หลังอัปเกรด library หรือย้ายเครื่องคนละสถาปัตยกรรม)
"""
import contextlib
import functools
import hashlib
import importlib.metadata
import io
import json
import platform
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CODE_FILES = ["modeling/tfp.py", "modeling/core.py", "compute.py", "jobs.py", "data_loader.py", "codec.py"]
NUMERIC = ["numpy", "pandas", "scipy", "statsmodels", "patsy"]


@functools.lru_cache(maxsize=None)
def code_version() -> str:
    h = hashlib.sha256()
    for f in CODE_FILES:
        h.update(f.encode())
        h.update((APP_DIR / f).read_bytes())
    return h.hexdigest()[:16]


@functools.lru_cache(maxsize=None)
def runtime_fingerprint() -> str:
    import numpy
    import scipy

    def blas(module):
        with contextlib.redirect_stdout(io.StringIO()):
            cfg = module.show_config(mode="dicts")
        deps = cfg.get("Build Dependencies", {})
        return {k: deps.get(k) for k in ("blas", "lapack")}

    ident = {"machine": platform.machine(), "system": platform.system(), "python": sys.version,
             "libc": list(platform.libc_ver()),
             "packages": {p: importlib.metadata.version(p) for p in NUMERIC},
             "blas": {"numpy": blas(numpy), "scipy": blas(scipy)}}
    return hashlib.sha256(json.dumps(ident, sort_keys=True, default=str).encode()).hexdigest()[:16]
