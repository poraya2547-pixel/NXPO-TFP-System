"""ตรวจไลบรารี Python ใน backend/requirements.lock กับฐานช่องโหว่ OSV (https://osv.dev)

ส่งออกไปเฉพาะชื่อแพ็กเกจ + เวอร์ชัน (ไม่มีโค้ด/ข้อมูล/คีย์) แล้วพิมพ์รายการช่องโหว่ที่ตรงเวอร์ชัน

    /opt/anaconda3/envs/idntwww/bin/python -B tools/security/osv_python.py
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "backend" / "requirements.lock"
pkgs = [m.groups() for m in (re.match(r"^([A-Za-z0-9_.-]+)==([^\s;#]+)", l) for l in LOCK.read_text().splitlines()) if m]
body = {"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in pkgs]}
req = urllib.request.Request("https://api.osv.dev/v1/querybatch", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
res = json.loads(urllib.request.urlopen(req, timeout=60).read())["results"]
found = 0
for (name, ver), r in zip(pkgs, res):
    ids = [v["id"] for v in r.get("vulns", [])]
    if ids:
        found += 1
        detail = []
        for i in ids:
            d = json.loads(urllib.request.urlopen(f"https://api.osv.dev/v1/vulns/{i}", timeout=60).read())
            sev = (d.get("database_specific") or {}).get("severity") or ""
            fixed = sorted({e["fixed"] for a in d.get("affected", []) for rg in a.get("ranges", [])
                            for e in rg.get("events", []) if "fixed" in e})
            detail.append(f"    {i} [{sev}] fixed={','.join(fixed) or '-'} {d.get('summary', '')[:110]}")
        print(f"{name}=={ver}: {len(ids)} รายการ")
        print("\n".join(detail))
print(f"ตรวจ {len(pkgs)} แพ็กเกจ พบช่องโหว่ใน {found} แพ็กเกจ")
sys.exit(1 if found else 0)
