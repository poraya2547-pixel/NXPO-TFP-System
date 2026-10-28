"""เขียน docs/contracts/openapi.json จาก FastAPI app (ใช้ generate TypeScript types ของหน้าเว็บ)

ต้องรันใน image ของ backend (มี FastAPI) เช่น:
    docker run --rm --network none -v $PWD:/src:ro -v $PWD/docs/contracts:/out -w /src -e PYTHONPATH=/src/backend \
        <image> python -B -P tools/refactor/export_openapi.py /out/openapi.json
"""
import json
import sys

from app.main import app

spec = app.openapi()
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False, indent=1, sort_keys=True)
    f.write("\n")
print("เขียนแล้ว", sys.argv[1], len(spec["paths"]), "paths")
