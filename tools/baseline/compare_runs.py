"""ตรวจและเทียบผล oracle สองชุดแบบตรงทุกบิต ภายใน runtime เดียวกันเท่านั้น

reference แยกตาม runtime: docs/baseline/ = Mac (env idntwww), docs/baseline/<ชุด>/ = runtime อื่น
แต่ละชุดมี baseline_conditions.json, oracle_baseline_hashes.json และ runtime.json

ไม่เชื่อ hash ที่เก็บในไฟล์อย่างเดียว:
- คำนวณ hash ใหม่จากเนื้อหา และเทียบเนื้อหาจริงทีละค่า
- ตรวจว่าผลครบตามรายการใน baseline_conditions.json ไม่ขาดไม่เกิน
- ตรวจเงื่อนไขของ baseline: PYTHONHASHSEED, Python, เวอร์ชัน package, snapshot, source เดิม,
  การตัดผล h=15 และตัวห่อ ARIMA
- runtime ของผลต้องตรงกับ runtime.json ของชุด (เครื่อง, build ของ Python/package, BLAS/LAPACK, env)
- ชุดอ้างอิงต้องตรงกับ hash ที่บันทึกไว้ใน oracle_baseline_hashes.json

    /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/compare_runs.py baseline <ชื่อผลใหม่>
    python -B tools/baseline/compare_runs.py <ชื่อ reference> <ชื่อผลใหม่> linux-arm64   # ใน image runtime
exit code 0 เมื่อผ่านทุกข้อเท่านั้น
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "private" / "baseline"
DOCS = REPO / "docs" / "baseline"
sys.path.insert(0, str(HERE))
import fingerprint  # noqa: E402
import replay  # noqa: E402

META_FIELDS = ["hash_seed", "python", "packages", "snapshot_sha256"]


def first_difference(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: ชนิดต่างกัน"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: มีแค่ฝั่งเดียว"
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: ความยาว {len(a)} กับ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: ค่าต่างกัน"


def check_runtime(run: dict, runtime_ref: dict, label: str, is_reference: bool) -> list:
    """runtime ของผลต้องตรงกับ runtime ที่ตรึงไว้กับชุด reference (ทุกช่องที่มีผลต่อการคำนวณ)
    ผลอ้างอิงที่ตรึงก่อนมีการบันทึก runtime (baseline Mac 9 ต.ค.) ยกเว้นได้เฉพาะฝั่งอ้างอิง
    เพราะเนื้อหาถูกตรวจกับ hash ที่ตรึงไว้แล้ว และ runtime.json ของชุดนั้นมาจากรอบที่ให้ผลตรงกันทุกค่า"""
    import runtime_info

    if runtime_ref is None:
        return [(False, f"[{label}] ชุด reference ไม่มี runtime.json — ระบุ runtime ไม่ได้ ใช้เทียบไม่ได้")]
    if "runtime" not in run:
        return [] if is_reference else [(False, f"[{label}] ไม่มีข้อมูล runtime ในผลชุดนี้")]
    got, want = runtime_info.comparable(run["runtime"]), runtime_ref["identity"]
    diff = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
    return [(not diff, f"[{label}] runtime ตรงกับ reference ({runtime_ref['name']})"
             + (f" · ต่างที่ {diff}" if diff else ""))]


def check_run(run: dict, cond: dict, anchor: dict, label: str, is_reference: bool, runtime_ref=None) -> list:
    checks = check_runtime(run, runtime_ref, label, is_reference)

    def add(ok, text):
        checks.append((bool(ok), f"[{label}] {text}"))

    outputs = run.get("outputs") or {}
    hashes = run.get("output_hashes") or {}
    expected = set(cond["output_keys"])
    missing, extra = sorted(expected - set(outputs)), sorted(set(outputs) - expected)
    add(not missing and not extra, f"ผลครบ {len(expected)} ค่า"
        + (f" · ขาด {missing}" if missing else "") + (f" · เกิน {extra}" if extra else ""))
    add(set(hashes) == set(outputs), "รายการ hash ตรงกับรายการผล")
    stale = sorted(k for k in outputs if hashes.get(k) != fingerprint.sha256_canonical(outputs[k]))
    add(not stale, "hash ที่เก็บตรงกับเนื้อหาจริง" + (f" · ไม่ตรง {stale}" if stale else ""))

    slices = run.get("slice_identical") or {}
    add(set(slices) == set(cond["horizons"]) and all(v is True for v in slices.values()),
        "ตัดผลจาก h=15 ตรงกับทุก horizon")
    add(run.get("instrumentation_neutral") is True, "ตัวห่อ ARIMA ไม่เปลี่ยนตัวเลข")
    add(run.get("source_hashes") == anchor["source_hashes"], "ฟังก์ชันจากไฟล์แอปเป็น source เดิม")
    add(run.get("file_hashes") == anchor["file_hashes"], "ไฟล์แอป / TFP.py / data_loader.py ไม่ถูกแก้")

    if all(f in run for f in META_FIELDS):
        add(run["hash_seed"] == cond["hash_seed"], f"PYTHONHASHSEED = {cond['hash_seed']}")
        add(run["python"] == cond["python"], f"Python {cond['python']}")
        add(run["packages"] == cond["packages"], "เวอร์ชัน numpy/pandas/scipy/statsmodels/patsy ตรงกับ baseline")
        add(run["snapshot_sha256"] == cond["snapshot_sha256"], "ใช้ snapshot เดียวกับ baseline")
    elif not is_reference:
        add(False, "ไม่มีข้อมูลเงื่อนไข (seed/Python/package/snapshot) ในผลชุดนี้")
    if is_reference:
        add(hashes == anchor["output_hashes"], "ตรงกับ baseline ที่บันทึกใน docs/baseline ทุกค่า")
    return checks


def verify(ref_name: str, cand_name: str, out_dir: Path = OUT, docs_dir: Path = DOCS) -> list:
    cond = json.loads((docs_dir / "baseline_conditions.json").read_text(encoding="utf-8"))
    anchor = json.loads((docs_dir / "oracle_baseline_hashes.json").read_text(encoding="utf-8"))
    rt_path = docs_dir / "runtime.json"
    runtime_ref = json.loads(rt_path.read_text(encoding="utf-8")) if rt_path.exists() else None
    runs, checks = {}, []
    for label, name in (("อ้างอิง", ref_name), ("ผลใหม่", cand_name)):
        path = Path(out_dir) / f"oracle_{name}.json"
        if not path.exists():
            checks.append((False, f"[{label}] ไม่พบไฟล์ {path.name}"))
            continue
        runs[label] = json.loads(path.read_text(encoding="utf-8"))
        checks += check_run(runs[label], cond, anchor, label, is_reference=(label == "อ้างอิง"),
                            runtime_ref=runtime_ref)

    tabs_sha = fingerprint.sha256(replay.load_tabs())
    checks.append((tabs_sha == cond["snapshot_sha256"], "[snapshot] ไฟล์ snapshot ของ baseline ไม่ถูกแก้"))

    if len(runs) == 2:
        ref, cand = runs["อ้างอิง"], runs["ผลใหม่"]
        keys = cond["output_keys"]
        diffs, matched = [], 0
        for k in keys:
            a, b = (ref.get("outputs") or {}).get(k), (cand.get("outputs") or {}).get(k)
            if a is None or b is None:
                continue
            d = first_difference(a, b)
            if d:
                diffs.append(f"{k} -> {d}")
            else:
                matched += 1
        checks.append((matched == len(keys), f"[เทียบ] เนื้อหาผลตรงกัน {matched}/{len(keys)} ค่า"
                       + ("".join(f"\n      ต่าง: {x}" for x in diffs))))
        checks.append((ref.get("fit_groups") == cand.get("fit_groups"),
                       "[เทียบ] บันทึก fit ARIMA (converge/คำเตือน) ตรงกัน"))
    return checks


def main(ref_name: str, cand_name: str, ref_set: str = "") -> int:
    docs_dir = DOCS / ref_set if ref_set else DOCS
    if not (docs_dir / "baseline_conditions.json").exists():
        sys.exit(f"ไม่พบชุด reference {docs_dir}")
    checks = verify(ref_name, cand_name, docs_dir=docs_dir)
    for ok, text in checks:
        print(("ผ่าน     " if ok else "ไม่ผ่าน  ") + text)
    failed = sum(1 for ok, _ in checks if not ok)
    print(f"\nสรุป: ผ่าน {len(checks) - failed}/{len(checks)} ข้อ" + ("" if failed else " · ใช้เทียบได้"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    # ชุด reference: ไม่ระบุ = docs/baseline (Mac idntwww); ระบุชื่อโฟลเดอร์ย่อย เช่น linux-arm64
    if len(sys.argv) not in (3, 4):
        sys.exit("ใช้: compare_runs.py <ชื่อชุดอ้างอิง> <ชื่อผลใหม่> [ชุด reference เช่น linux-arm64]")
    sys.exit(main(*sys.argv[1:]))
