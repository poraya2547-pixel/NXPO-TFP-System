"""ภาพเทียบหน้าจอ: ซ้าย = ระบบเดิม (ชุด baseline) ขวา = ระบบใหม่ — ช่วยตรวจด้วยตา ไม่ใช่ตัวตัดสินผ่าน/ไม่ผ่าน

    /opt/anaconda3/envs/idntwww/bin/python -B tools/refactor/compare_screens.py <ชุดเดิม> <ชุดใหม่> <โฟลเดอร์ผล>
"""
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
SCREENS = REPO / "private" / "baseline" / "ui" / "screens"


def main(base_set, new_set, out_dir):
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for dev, scale in (("desktop", 0.5), ("mobile", 0.8)):
        for f in sorted((SCREENS / base_set / dev).glob("*.png")):
            n = SCREENS / new_set / dev / f.name
            if not n.exists():
                continue
            a, b = Image.open(f).convert("RGB"), Image.open(n).convert("RGB")
            a = a.resize((int(a.width * scale), int(a.height * scale)))
            b = b.resize((int(b.width * scale), int(b.height * scale)))
            c = Image.new("RGB", (a.width + b.width + 20, max(a.height, b.height)), (255, 0, 255))
            c.paste(a, (0, 0))
            c.paste(b, (a.width + 20, 0))
            p = out / f"{dev}_{f.stem}.png"
            if p.exists():
                raise FileExistsError(p)
            c.save(p)
            print(p.relative_to(REPO), a.size, b.size)


if __name__ == "__main__":
    main(*sys.argv[1:4])
