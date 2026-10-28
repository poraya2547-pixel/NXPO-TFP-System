"""เทียบผลเก็บหน้าจอ (ui_capture.py) กับเงื่อนไขที่ตรึงไว้ และเทียบสองชุดแบบตรงทุกค่า

ยึด docs/baseline/ui_conditions.json (ตรึงจากชุดที่ตรวจแล้วด้วย freeze_baseline.py ui):
- แต่ละชุดต้องมีสถานะตรงรายชื่อที่ตรึงไว้ครบทุกชื่อ ไม่ขาดไม่เกิน สองชุดที่ว่างหรือขาดเหมือนกันจึงไม่ผ่าน
- metadata ต้องมีและตรงกับที่ตรึงไว้: PYTHONHASHSEED, เวลาที่ใช้แทนการกดดึงข้อมูล, log ที่ใช้
- runtime ของชุดต้องตรงกับ runtime.json ของชุด reference (แยก reference ตาม runtime เหมือนตัวเลข)
- ชุดอ้างอิงต้องเป็นชุดที่ตรึงไว้จริง: hash ของไฟล์ manifest ตรงกับที่บันทึก
- hash ใน manifest ต้องตรงกับไฟล์ ไม่มี exception และเนื้อหาทุกสถานะตรงกัน
ไม่เชื่อ hash ใน manifest อย่างเดียว: คำนวณจากไฟล์ใหม่และเทียบเนื้อหาจริง

ข้อยกเว้นเดียวตอนเทียบ: widget id ของ Streamlit มีรูป $$ID-<hash 32 ตัว>-<key> โดย hash ขึ้นกับ path
ของไฟล์แอป ย้ายโฟลเดอร์แล้ว id เปลี่ยนทั้งที่หน้าจอเหมือนเดิม จึงแทนเฉพาะ hash ส่วนนั้นก่อนเทียบ
key ของ widget และค่าอื่นทั้งหมดยังเทียบตรงทุกตัว ไฟล์ที่เก็บไว้ไม่ถูกแก้

    /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/ui_compare.py <ชุดอ้างอิง> <ชุดใหม่>
exit code 0 เมื่อผ่านทุกข้อเท่านั้น
"""
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "private" / "baseline" / "ui"
CONDITIONS = HERE.parents[1] / "docs" / "baseline" / "ui_conditions.json"
sys.path.insert(0, str(HERE))
from compare_runs import first_difference  # noqa: E402

WIDGET_ID_HASH = re.compile(r"\$\$ID-[0-9a-f]{32}-")
META = {"hash_seed": "PYTHONHASHSEED = 0", "fixed_loaded_at": "เวลาที่ใช้แทนการกดดึงข้อมูลตรงกับที่ตรึงไว้",
        "fetch_log_sha256": "ใช้ fetch_log ชุด baseline"}


def without_path_hash(obj):
    if isinstance(obj, dict):
        return {k: without_path_hash(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [without_path_hash(v) for v in obj]
    if isinstance(obj, str):
        return WIDGET_ID_HASH.sub("$$ID-<path-hash>-", obj)
    return obj


def load_run(name: str, out_dir: Path = OUT):
    """อ่านเฉพาะสถานะที่มีทั้งใน manifest และมีไฟล์จริง ที่ขาดไฟล์จะไปตกที่การตรวจความครบ"""
    d = Path(out_dir) / name
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    states = {}
    for state in manifest.get("captures") or {}:
        path = d / f"{state}.json"
        if path.exists():
            text = path.read_text(encoding="utf-8")
            states[state] = (hashlib.sha256(text.encode("utf-8")).hexdigest(), json.loads(text))
    return manifest, states


def verify(ref: str, cand: str, out_dir: Path = OUT, conditions: Path = CONDITIONS) -> list:
    from compare_runs import check_runtime

    cond = json.loads(Path(conditions).read_text(encoding="utf-8"))
    rt_path = Path(conditions).parent / "runtime.json"
    runtime_ref = json.loads(rt_path.read_text(encoding="utf-8")) if rt_path.exists() else None
    expected = cond["states"]
    checks = []
    runs = {}
    for label, name in (("อ้างอิง", ref), ("ชุดใหม่", cand)):
        if not (Path(out_dir) / name / "manifest.json").exists():
            checks.append((False, f"[{label}] ไม่พบชุด {name} หรือเก็บไม่ครบ (ไม่มี manifest)"))
            continue
        manifest, states = load_run(name, out_dir)
        runs[label] = (manifest, states)
        checks += check_runtime(manifest, runtime_ref, label, is_reference=(label == "อ้างอิง"))
        for key, text in META.items():
            checks.append((key in manifest and manifest[key] == cond[key], f"[{label}] {text}"))
        missing = [s for s in expected if s not in states]
        extra = sorted(set(states) - set(expected))
        checks.append((not missing and not extra, f"[{label}] สถานะครบ {len(expected)} ชื่อตามที่ตรึงไว้"
                       + (f" · ขาด {missing}" if missing else "") + (f" · เกิน {extra}" if extra else "")))
        stale = [s for s, (h, _) in states.items() if manifest["captures"][s].get("sha256") != h]
        checks.append((not stale, f"[{label}] hash ใน manifest ตรงกับไฟล์" + (f" · ไม่ตรง {stale}" if stale else "")))
        errs = [s for s, (_, c) in states.items() if c.get("exceptions")]
        checks.append((not errs, f"[{label}] ไม่มี exception" + (f" · มีใน {errs}" if errs else "")))
    if "อ้างอิง" in runs:
        sha = hashlib.sha256((Path(out_dir) / ref / "manifest.json").read_bytes()).hexdigest()
        checks.append((sha == cond["reference"]["manifest_sha256"],
                       f"[อ้างอิง] เป็นชุดที่ตรึงไว้ ({cond['reference']['run']}) — hash ของ manifest ตรง"))
    if len(runs) == 2:
        (_, s1), (_, s2) = runs["อ้างอิง"], runs["ชุดใหม่"]
        diffs, matched = [], 0
        for state in expected:
            if state not in s1 or state not in s2:
                continue
            d = first_difference(without_path_hash(s1[state][1]), without_path_hash(s2[state][1]))
            if d:
                diffs.append(f"{state} -> {d}")
            else:
                matched += 1
        checks.append((matched == len(expected), f"[เทียบ] เนื้อหาตรงกัน {matched}/{len(expected)} สถานะ"
                       + "".join(f"\n      ต่าง: {x}" for x in diffs)))
    return checks


def main(ref: str, cand: str, ref_set: str = "") -> int:
    conditions = CONDITIONS.parent / ref_set / "ui_conditions.json" if ref_set else CONDITIONS
    checks = verify(ref, cand, conditions=conditions)
    for ok, text in checks:
        print(("ผ่าน     " if ok else "ไม่ผ่าน  ") + text)
    failed = sum(1 for ok, _ in checks if not ok)
    print(f"\nสรุป: ผ่าน {len(checks) - failed}/{len(checks)} ข้อ")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    # ชุด reference: ไม่ระบุ = docs/baseline (Mac idntwww); ระบุชื่อโฟลเดอร์ย่อย เช่น linux-arm64
    if len(sys.argv) not in (3, 4):
        sys.exit("ใช้: ui_compare.py <ชุดอ้างอิง> <ชุดใหม่> [ชุด reference เช่น linux-arm64]")
    sys.exit(main(*sys.argv[1:]))
