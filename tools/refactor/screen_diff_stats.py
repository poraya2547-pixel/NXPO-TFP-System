"""สถิติความต่างของภาพหน้าจอระหว่างสองชุด (ใช้ประกอบการตรวจด้วยตา ไม่ใช่เกณฑ์ผ่าน/ไม่ผ่าน)

ต่อภาพ: ขนาด, สัดส่วนพิกเซลที่ต่างเกิน 15 ระดับ (เทียบเฉพาะส่วนที่ซ้อนกัน), กรอบที่ต่าง, และความสูงช่วงบนที่ตรงกันทุกพิกเซล
ชุดที่จะเทียบควรถ่ายด้วย Chrome ตัวเดียวกันและตัวเลือกเดียวกัน (ธีม/โปรไฟล์สี) ไม่งั้นต่างเพราะสภาพแวดล้อม

    /opt/anaconda3/envs/idntwww/bin/python -B tools/refactor/screen_diff_stats.py <ชุดเดิม> <ชุดใหม่>
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops

REPO = Path(__file__).resolve().parents[2]
SCREENS = REPO / "private" / "baseline" / "ui" / "screens"
THRESHOLD = 16


def stats(a: Image.Image, b: Image.Image) -> dict:
    w, h = min(a.width, b.width), min(a.height, b.height)
    d = ImageChops.difference(a.crop((0, 0, w, h)), b.crop((0, 0, w, h))).convert("L")
    hist = d.histogram()
    mask = d.point(lambda v: 255 if v >= THRESHOLD else 0)
    bbox = mask.getbbox()
    return {"pct": 100 * sum(hist[THRESHOLD:]) / (w * h), "bbox": bbox,
            "same_top": h if bbox is None else bbox[1]}


def main(base_set: str, new_set: str) -> int:
    rows = 0
    for dev in ("desktop", "mobile"):
        for f in sorted((SCREENS / base_set / dev).glob("*.png")):
            g = SCREENS / new_set / dev / f.name
            if not g.exists():
                print(f"{dev:7} {f.stem:32} (ไม่มีในชุดใหม่)")
                continue
            a, b = Image.open(f).convert("RGB"), Image.open(g).convert("RGB")
            s = stats(a, b)
            size = "ขนาดเท่ากัน" if a.size == b.size else f"{a.size} vs {b.size}"
            print(f"{dev:7} {f.stem:32} {size:28} ต่าง {s['pct']:6.2f}%  ตรงกันช่วงบน {s['same_top']:5d}px  กรอบ {s['bbox']}")
            rows += 1
    return 0 if rows else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
