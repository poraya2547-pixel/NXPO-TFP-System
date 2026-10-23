"""เขียนไฟล์ผล baseline แบบห้ามทับของเดิม"""
import re
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def check_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise ValueError(f"ชื่อ '{name}' ใช้ไม่ได้ (ใช้ได้เฉพาะ A-Z a-z 0-9 _ - และห้ามว่าง)")
    return name


def ensure_absent(paths) -> None:
    existing = [str(p) for p in paths if Path(p).exists()]
    if existing:
        raise FileExistsError("มีไฟล์ชื่อนี้อยู่แล้ว ไม่เขียนทับ: " + ", ".join(existing))


def write_new(path, data) -> None:
    """สร้างไฟล์ใหม่เท่านั้น ถ้ามีอยู่แล้วจะล้มโดยไม่แตะไฟล์เดิม (open แบบ 'x')"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        with open(path, "xb") as f:
            f.write(data)
    else:
        with open(path, "x", encoding="utf-8") as f:
            f.write(data)
