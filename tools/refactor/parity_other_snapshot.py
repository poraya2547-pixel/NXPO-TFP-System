"""Step 5 (แผน §9A "แก้ค่าในปีเดิมเป็น B แล้วกดดึง → ผลตรง old engine บน B"): เทียบโค้ดต้นฉบับกับโค้ดใหม่บนข้อมูลที่ถูกแก้

ชุด B = snapshot เดิม (private/baseline/sheets_raw.json) ที่แก้ค่า TFPI ปี 2010 หนึ่งช่อง (+1.0) ปีและจำนวนแถวเท่าเดิม
- ฝั่งเดิม: tools/baseline/oracle.run (TFP.py + data_loader.py + ฟังก์ชันของ TFP_App1.3.0.py ตามลำดับเดิม)
- ฝั่งใหม่: backend/tests/parity.run_candidate (backend/app)
ทั้งสองฝั่งอ่าน B ด้วย loader ของตัวเอง (แทนเฉพาะ client ที่อ่านชีต) รันใน process และ runtime เดียวกัน แล้วเทียบผลดิบทุกค่า
แบบไม่มี tolerance รวมบันทึก fit ARIMA — ไม่ใช่ reference ที่ตรึง (ไม่เขียนใน docs/baseline)
ผล (มีค่าข้อมูล) อยู่ที่ <โฟลเดอร์ผล> (ค่าเริ่มต้น private/verification/<ชื่อ>/) ห้ามทับ

    PYTHONHASHSEED=0 /opt/anaconda3/envs/idntwww/bin/python -B -P tools/refactor/parity_other_snapshot.py <ชื่อ> [โฟลเดอร์ผล]
"""
import copy
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tools" / "baseline"), str(REPO / "backend" / "tests"), str(REPO / "backend")]
import fingerprint  # noqa: E402
import oracle  # noqa: E402
import parity  # noqa: E402
import replay  # noqa: E402
import runtime_info  # noqa: E402
import safe_io  # noqa: E402
from compare_runs import first_difference  # noqa: E402

CHANGE = {"tab": "Data", "year": "2010", "column": "TFPI", "add": 1.0}


def snapshot_b(tabs_a):
    tabs = copy.deepcopy(tabs_a)
    data = tabs[CHANGE["tab"]]
    col = data[0].index(CHANGE["column"])
    row = next(r for r in data if r[0] == CHANGE["year"])
    row[col] = repr(float(row[col]) + CHANGE["add"])
    return tabs


def main(name, out=None):
    if os.environ.get("PYTHONHASHSEED") != "0":
        sys.exit("ต้องรันด้วย PYTHONHASHSEED=0")
    out = Path(out) if out else REPO / "private" / "verification" / safe_io.check_name(name)
    files = [out / "sheets_raw_B.json", out / f"oracle_{name}.json", out / f"candidate_{name}.json", out / "compare.json"]
    safe_io.ensure_absent(files)
    out.mkdir(parents=True, exist_ok=True)
    tabs_a = replay.load_tabs()
    tabs_b = snapshot_b(tabs_a)
    safe_io.write_new(files[0], json.dumps({"derived_from_sha256": fingerprint.sha256(tabs_a), "change": CHANGE,
                                            "tabs": tabs_b}, ensure_ascii=False))
    replay.load_tabs = lambda path=None: copy.deepcopy(tabs_b)   # ทั้งสองฝั่งอ่านชุด B
    oracle.OUT = out
    oracle.run(name)
    old = json.loads(files[1].read_text(encoding="utf-8"))
    new = parity.run_candidate()
    safe_io.write_new(files[2], json.dumps(dict(new, run=name), ensure_ascii=False))

    checks = [(fingerprint.sha256(tabs_b) != fingerprint.sha256(tabs_a), "ชุด B ต่างจาก snapshot เดิม"),
              (old["snapshot_sha256"] == new["snapshot_sha256"] == fingerprint.sha256(tabs_b), "ทั้งสองฝั่งอ่านชุด B"),
              (runtime_info.comparable(old["runtime"]) == runtime_info.comparable(new["runtime"]), "runtime เดียวกัน"),
              (old["hash_seed"] == new["hash_seed"] == "0", "PYTHONHASHSEED = 0"),
              (all(old["slice_identical"].values()) == new["flags"]["slice_identical"]
               and old["instrumentation_neutral"] == new["flags"]["instrumentation_neutral"], "ธงตรวจตรงกัน")]
    keys = sorted(old["outputs"])
    checks.append((keys == sorted(new["outputs"]), f"ผลครบ {len(keys)} ค่าทั้งสองฝั่ง"))
    diffs = [f"{k} -> {d}" for k in keys if k in new["outputs"]
             for d in [first_difference(old["outputs"][k], new["outputs"][k])] if d]
    checks.append((not diffs, f"เนื้อหาตรงทุกบิต {len(keys) - len(diffs)}/{len(keys)} ค่า" + "".join(f"\n      ต่าง: {x}" for x in diffs)))
    checks.append((old["fit_groups"] == new["fit_groups"], "บันทึก fit ARIMA (converge/คำเตือน) ตรงกัน"))
    # ข้อมูลที่แก้มีผลจริง: ค่าที่ต่างจาก reference ของชุดเดิมบน runtime นี้ (ข้อมูลประกอบ ไม่ใช่เกณฑ์)
    ref_dir = parity.reference_set()
    changed = None
    if ref_dir is not None:
        anchor = json.loads((ref_dir / "oracle_baseline_hashes.json").read_text(encoding="utf-8"))
        ref_a = json.loads((REPO / "private" / "baseline" / f"oracle_{anchor['run']}.json").read_text(encoding="utf-8"))
        changed = [k for k in keys if first_difference(ref_a["outputs"][k], old["outputs"][k])]
    safe_io.write_new(files[3], json.dumps({"checks": [[ok, t] for ok, t in checks], "changed_vs_snapshot_a": changed,
                                            "reference_set_a": str(ref_dir.relative_to(REPO)) if ref_dir else None},
                                           ensure_ascii=False, indent=1))
    for ok, text in checks:
        print(("ผ่าน     " if ok else "ไม่ผ่าน  ") + text)
    print(f"ค่าที่เปลี่ยนจากชุดเดิม ({len(changed or [])}): {changed}")
    failed = sum(1 for ok, _ in checks if not ok)
    print(f"สรุป: ผ่าน {len(checks) - failed}/{len(checks)} ข้อ · ผลอยู่ที่ {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
