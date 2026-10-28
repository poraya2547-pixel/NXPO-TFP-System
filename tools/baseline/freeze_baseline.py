"""ตรึง baseline จากผลที่ผ่านเงื่อนไข ห้ามทับไฟล์เดิม ใช้ครั้งเดียวตอนตั้ง reference ของแต่ละ runtime

reference ต้องมาจาก oracle ของโค้ดต้นฉบับเท่านั้น (ห้ามตรึงจากผลของโค้ดใหม่) และไม่สร้างใหม่อัตโนมัติเมื่อ test ตก

- ตัวเลข (Mac): ผล oracle → docs/baseline/baseline_conditions.json และ oracle_baseline_hashes.json
- runtime ของชุดที่มีอยู่แล้ว: ผล oracle รอบใหม่ที่ hash ตรงกับ reference ทุกค่า → <ชุด>/runtime.json
- ชุด reference ของ runtime อื่น: ผล oracle (ต้องมี runtime) → docs/baseline/<ชุด>/ ทั้ง 3 ไฟล์
- หน้าจอ: ชุด ui_capture → docs/baseline/ui_conditions.json (ui_compare.py ใช้)
หลังตรึงต้องรันชุดใหม่แล้วเทียบด้วย compare_runs.py / ui_compare.py ว่าผ่านทุกข้อ

    /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/freeze_baseline.py baseline
    /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/freeze_baseline.py ui ui-baseline
    /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/freeze_baseline.py runtime <ผล oracle รอบใหม่>
    python -B tools/baseline/freeze_baseline.py set <ผล oracle ใน runtime นั้น> <ชุด เช่น linux-arm64>
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "private" / "baseline"
UI_OUT = OUT / "ui"
DOCS = REPO / "docs" / "baseline"
sys.path.insert(0, str(HERE))
import runtime_info  # noqa: E402
import safe_io  # noqa: E402

# ต้นฉบับที่ใช้ตรึงชุดใหม่ (ชุดที่ตรึงแล้วบันทึก source ของตัวเองไว้ในไฟล์ชุดนั้น): e6aee03 → 7bf84e4 ตั้งแต่ 10 ต.ค. 2026 → acc64ee → 4c8aa71 (20 ต.ค.)
SOURCE = {"repo": "https://github.com/poraya2547-pixel/NXPO-TFP-System",
          "commit": "4c8aa71a2cec89208f40d13e19f75eb520b75aac", "app_file": "TFP_App1.3.0.py"}


def _load_run(name: str) -> dict:
    return json.loads((OUT / f"oracle_{safe_io.check_name(name)}.json").read_text(encoding="utf-8"))


def _check_run(run: dict) -> None:
    problems = []
    if run.get("hash_seed") != "0":
        problems.append("PYTHONHASHSEED ไม่ใช่ 0")
    if not run.get("slice_identical") or not all(v is True for v in run["slice_identical"].values()):
        problems.append("ตัดผลจาก h=15 ไม่ตรงทุก horizon")
    if run.get("instrumentation_neutral") is not True:
        problems.append("ตัวห่อ ARIMA เปลี่ยนตัวเลข")
    if problems:
        raise ValueError("ตรึงไม่ได้: " + ", ".join(problems))


def _runtime_doc(run: dict, name: str, set_name: str) -> dict:
    return {
        "note": "runtime ที่ reference ชุดนี้ผูกอยู่ ผลจาก runtime อื่นใช้เทียบกับชุดนี้ไม่ได้ (ตรวจโดย compare_runs.py)",
        "name": set_name, "created_from_run": name, "declared_image": run["runtime"].get("declared_image"),
        "identity": runtime_info.comparable(run["runtime"]),
    }


def _write(paths_data: list) -> list:
    safe_io.ensure_absent([p for p, _ in paths_data])
    for path, data in paths_data:
        safe_io.write_new(path, json.dumps(data, ensure_ascii=False, indent=1))
        path.chmod(0o444)
    return [p for p, _ in paths_data]


def freeze(name: str, docs: Path = DOCS, set_name: str = "mac-idntwww") -> list:
    run = _load_run(name)
    _check_run(run)
    docs = Path(docs)
    cond = {
        "note": "เงื่อนไขที่ baseline ผูกอยู่ ผลที่ไม่ผ่านเงื่อนไขเหล่านี้ใช้เทียบไม่ได้ (ตรวจโดย compare_runs.py)",
        "source": SOURCE, "hash_seed": run["hash_seed"], "python": run["python"], "packages": run["packages"],
        "snapshot_sha256": run["snapshot_sha256"], "horizons": sorted(run["slice_identical"], key=int),
        "output_keys": sorted(run["outputs"]),
        "required_flags": {"slice_identical": True, "instrumentation_neutral": True},
    }
    anchor = {
        "run": name, "source": SOURCE, "hash_seed": run["hash_seed"], "env": set_name,
        "source_hashes": run["source_hashes"], "file_hashes": run["file_hashes"], "output_hashes": run["output_hashes"],
        "slice_identical": run["slice_identical"], "instrumentation_neutral": run["instrumentation_neutral"],
        "fit_counts": {g: {"fits": len(f), "not_converged": sum(1 for x in f if x.get("converged") is False)}
                       for g, f in run["fit_groups"].items()},
    }
    files = [(docs / "baseline_conditions.json", cond), (docs / "oracle_baseline_hashes.json", anchor)]
    if "runtime" in run:
        files.append((docs / "runtime.json", _runtime_doc(run, name, set_name)))
    if docs != DOCS:
        docs.mkdir(parents=True, exist_ok=True)
    return _write(files)


def freeze_runtime(name: str, docs: Path = DOCS, set_name: str = "mac-idntwww") -> list:
    """ตรึง runtime.json ให้ชุดที่ตรึงไว้ก่อนมีการบันทึก runtime: ผลรอบใหม่ต้องตรง reference ทุกค่า"""
    run = _load_run(name)
    _check_run(run)
    if "runtime" not in run:
        raise ValueError("ตรึงไม่ได้: ผลชุดนี้ไม่มีข้อมูล runtime")
    docs = Path(docs)
    cond = json.loads((docs / "baseline_conditions.json").read_text(encoding="utf-8"))
    anchor = json.loads((docs / "oracle_baseline_hashes.json").read_text(encoding="utf-8"))
    problems = [k for k in ("hash_seed", "python", "packages", "snapshot_sha256") if run.get(k) != cond[k]]
    if run.get("output_hashes") != anchor["output_hashes"]:
        problems.append("ผลไม่ตรงกับ hash ที่ตรึงไว้")
    if run.get("source_hashes") != anchor["source_hashes"] or run.get("file_hashes") != anchor["file_hashes"]:
        problems.append("source/ไฟล์ต้นฉบับไม่ตรง")
    if problems:
        raise ValueError("ตรึง runtime ไม่ได้: " + ", ".join(problems))
    return _write([(docs / "runtime.json", _runtime_doc(run, name, set_name))])


def freeze_ui(name: str, docs: Path = DOCS) -> list:
    d = UI_OUT / safe_io.check_name(name)
    manifest_bytes = (d / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    captures = manifest.get("captures") or {}
    problems = []
    if manifest.get("hash_seed") != "0":
        problems.append("PYTHONHASHSEED ไม่ใช่ 0")
    if not captures:
        problems.append("ไม่มีสถานะ")
    for key in ("fixed_loaded_at", "fetch_log_sha256"):
        if not manifest.get(key):
            problems.append(f"ไม่มี {key}")
    for state, info in captures.items():
        path = d / f"{state}.json"
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != info.get("sha256"):
            problems.append(f"{state} ไฟล์หายหรือ hash ไม่ตรง")
        if info.get("exceptions"):
            problems.append(f"{state} มี exception")
    if problems:
        raise ValueError("ตรึงไม่ได้: " + ", ".join(problems))

    cond = {
        "note": "เงื่อนไข baseline หน้าจอ ชุดที่ไม่ผ่านเงื่อนไขเหล่านี้ใช้เทียบไม่ได้ (ตรวจโดย ui_compare.py)",
        "source": SOURCE,
        "reference": {"run": name, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()},
        "states": list(captures),
        "hash_seed": manifest["hash_seed"], "fixed_loaded_at": manifest["fixed_loaded_at"],
        "fetch_log_sha256": manifest["fetch_log_sha256"],
    }
    if "runtime" in manifest:
        cond["runtime_identity"] = runtime_info.comparable(manifest["runtime"])
        rt = Path(docs) / "runtime.json"
        if rt.exists() and json.loads(rt.read_text(encoding="utf-8"))["identity"] != cond["runtime_identity"]:
            raise ValueError("ตรึงไม่ได้: runtime ของชุดหน้าจอไม่ตรงกับ runtime.json ของชุด reference")
    return _write([(Path(docs) / "ui_conditions.json", cond)])


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        if len(args) == 1:
            written = freeze(args[0])
        elif len(args) in (2, 3) and args[0] == "ui":
            written = freeze_ui(args[1], DOCS / safe_io.check_name(args[2]) if len(args) == 3 else DOCS)
        elif len(args) in (2, 3) and args[0] == "runtime":
            set_name = args[2] if len(args) == 3 else ""
            written = freeze_runtime(args[1], DOCS / set_name if set_name else DOCS, set_name or "mac-idntwww")
        elif len(args) == 3 and args[0] == "set":
            written = freeze(args[1], DOCS / safe_io.check_name(args[2]), args[2])
        else:
            sys.exit("ใช้: freeze_baseline.py <ผล oracle> | ui <ชุดหน้าจอ> [ชุด] | runtime <ผล oracle> [ชุด] | set <ผล oracle> <ชุด>")
        for p in written:
            print(f"เขียนแล้ว {p.relative_to(REPO)}")
    except (FileExistsError, ValueError) as e:
        sys.exit(f"หยุด: {e}")
