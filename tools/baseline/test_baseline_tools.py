"""ทดสอบว่าเครื่องมือ baseline ตรวจตกจริงเมื่อผลผิด และไม่เขียนทับไฟล์เดิม

ไม่อ่าน Google Sheets ไม่คำนวณโมเดลใหม่: ใช้ไฟล์ baseline ที่มีอยู่ สร้างผลปลอมใน tmp แล้วแก้ทีละจุด

    /opt/anaconda3/envs/idntwww/bin/python -B -m pytest -p no:cacheprovider -q tools/baseline/test_baseline_tools.py
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import compare_runs  # noqa: E402
import fetch_snapshot  # noqa: E402
import fingerprint  # noqa: E402
import freeze_baseline  # noqa: E402
import oracle  # noqa: E402
import safe_io  # noqa: E402

PRIVATE = REPO / "private" / "baseline"
DOCS = REPO / "docs" / "baseline"
BASELINE = json.loads((PRIVATE / "oracle_baseline.json").read_text(encoding="utf-8"))
COND = json.loads((DOCS / "baseline_conditions.json").read_text(encoding="utf-8"))
RUNTIME = json.loads((DOCS / "runtime.json").read_text(encoding="utf-8"))
PROTECTED = ["sheets_raw.json", "raw_df_live.pkl", "snapshot_summary.json", "oracle_baseline.json"]
N_OUT = len(COND["output_keys"])
ONE_OFF = f"[เทียบ] เนื้อหาผลตรงกัน {N_OUT - 1}/{N_OUT}"


def candidate():
    """ผลจำลองที่รันใน runtime ของชุด Mac (ข้อมูล runtime มาจาก runtime.json ที่ตรึงไว้)"""
    c = copy.deepcopy(BASELINE)
    c.update(run="cand", hash_seed="0", python=COND["python"], packages=dict(COND["packages"]),
             snapshot_sha256=COND["snapshot_sha256"], runtime=dict(copy.deepcopy(RUNTIME["identity"]), declared_image=None))
    return c


def failures(tmp_path, cand, ref=None):
    (tmp_path / "oracle_baseline.json").write_text(json.dumps(ref or BASELINE, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "oracle_cand.json").write_text(json.dumps(cand, ensure_ascii=False), encoding="utf-8")
    return [text for ok, text in compare_runs.verify("baseline", "cand", out_dir=tmp_path) if not ok]


def nudge_first_number(canon_df):
    """เปลี่ยนบิตท้ายของตัวเลขจริงตัวแรกในตาราง (ข้าม NaN) ให้ต่างน้อยที่สุดที่เป็นไปได้"""
    for row in canon_df["values"]:
        for j, value in enumerate(row):
            if isinstance(value, str) and "0x" in value and "p" in value:
                mantissa, exp = value.split("p")
                row[j] = f"{mantissa[:-1]}{'1' if mantissa[-1] != '1' else '2'}p{exp}"
                return
    raise AssertionError("ไม่พบตัวเลขในตาราง")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------- ตัวเทียบ ----------

def test_identical_candidate_passes(tmp_path):
    assert failures(tmp_path, candidate()) == []


def test_changed_number_is_caught_even_if_hash_updated(tmp_path):
    c = candidate()
    nudge_first_number(c["outputs"]["forecast.h5"])
    c["output_hashes"]["forecast.h5"] = fingerprint.sha256_canonical(c["outputs"]["forecast.h5"])
    fails = failures(tmp_path, c)
    assert any(ONE_OFF in f and "forecast.h5" in f for f in fails)


def test_changed_number_with_stale_hash_is_caught(tmp_path):
    c = candidate()
    nudge_first_number(c["outputs"]["model_df"])
    fails = failures(tmp_path, c)
    assert any("hash ที่เก็บตรงกับเนื้อหาจริง" in f and "model_df" in f for f in fails)
    assert any(f.startswith("[เทียบ]") for f in fails)


def test_missing_output_is_caught(tmp_path):
    c = candidate()
    del c["outputs"]["rolling"], c["output_hashes"]["rolling"]
    fails = failures(tmp_path, c)
    assert any("ขาด ['rolling']" in f for f in fails)
    assert any(ONE_OFF in f for f in fails)


def test_extra_output_is_caught(tmp_path):
    c = candidate()
    c["outputs"]["extra"] = "x"
    c["output_hashes"]["extra"] = fingerprint.sha256_canonical("x")
    assert any("เกิน ['extra']" in f for f in failures(tmp_path, c))


@pytest.mark.parametrize("breaker, expected", [
    (lambda c: c["slice_identical"].update({"5": False}), "ตัดผลจาก h=15"),
    (lambda c: c["slice_identical"].pop("15"), "ตัดผลจาก h=15"),
    (lambda c: c.update(instrumentation_neutral=False), "ตัวห่อ ARIMA"),
    (lambda c: c.update(hash_seed="1"), "PYTHONHASHSEED"),
    (lambda c: c.update(python="3.12.13"), "Python"),
    (lambda c: c["packages"].update(statsmodels="0.14.2"), "เวอร์ชัน"),
    (lambda c: c.update(snapshot_sha256="0" * 64), "snapshot เดียวกับ baseline"),
    (lambda c: c["source_hashes"].update(_auto_arima_forecast="0" * 64), "source เดิม"),
    (lambda c: c["file_hashes"].update({"TFP.py": "0" * 64}), "ไม่ถูกแก้"),
    (lambda c: c.pop("hash_seed"), "ไม่มีข้อมูลเงื่อนไข"),
    (lambda c: c["fit_groups"]["holdout"][0].update(converged=not c["fit_groups"]["holdout"][0]["converged"]),
     "บันทึก fit ARIMA"),
    (lambda c: c["runtime"].update(machine="x86_64"), "runtime ตรงกับ reference"),
    (lambda c: c["runtime"]["compute_env"].update(OPENBLAS_NUM_THREADS="1"), "runtime ตรงกับ reference"),
    (lambda c: c["runtime"]["package_record_sha256"].update(numpy="0" * 64), "runtime ตรงกับ reference"),
    (lambda c: c.pop("runtime"), "ไม่มีข้อมูล runtime"),
], ids=["slice_false", "slice_missing", "instrumentation", "hash_seed", "python", "package",
        "snapshot", "source", "file", "no_metadata", "fit_log",
        "runtime_machine", "runtime_env", "runtime_build", "runtime_missing"])
def test_failed_condition_is_caught(tmp_path, breaker, expected):
    c = candidate()
    breaker(c)
    assert any(expected in f for f in failures(tmp_path, c))


def test_tampered_reference_is_caught(tmp_path):
    ref = copy.deepcopy(BASELINE)
    nudge_first_number(ref["outputs"]["forecast.h15"])
    ref["output_hashes"]["forecast.h15"] = fingerprint.sha256_canonical(ref["outputs"]["forecast.h15"])
    assert any("[อ้างอิง] ตรงกับ baseline ที่บันทึกใน docs/baseline" in f
               for f in failures(tmp_path, candidate(), ref=ref))


def test_declared_image_is_recorded_but_not_compared(tmp_path):
    c = candidate()
    c["runtime"]["declared_image"] = "sha256:" + "1" * 64
    assert failures(tmp_path, c) == []


def test_reference_set_without_runtime_is_rejected(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("baseline_conditions.json", "oracle_baseline_hashes.json"):
        shutil.copy(DOCS / name, docs / name)
    (tmp_path / "oracle_baseline.json").write_text(json.dumps(BASELINE, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "oracle_cand.json").write_text(json.dumps(candidate(), ensure_ascii=False), encoding="utf-8")
    fails = [t for ok, t in compare_runs.verify("baseline", "cand", out_dir=tmp_path, docs_dir=docs) if not ok]
    assert any("ไม่มี runtime.json" in f for f in fails)


LINUX = DOCS / "linux-arm64"
REAL_RUNS = ["linux-arm64-ref-1", "linux-arm64-ref-2", "mac-runtime-20261009"]


@pytest.mark.skipif(not all((PRIVATE / f"oracle_{n}.json").exists() for n in REAL_RUNS), reason="ยังไม่มีผลจริงของชุด runtime")
def test_real_runtime_sets():
    """ผลจริง: รอบซ้ำใน runtime เดียวกันผ่าน และข้าม runtime ต้องตกที่ runtime ทั้งสองทาง"""
    ok_linux = [t for ok, t in compare_runs.verify("linux-arm64-ref-1", "linux-arm64-ref-2", docs_dir=LINUX) if not ok]
    ok_mac = [t for ok, t in compare_runs.verify("baseline", "mac-runtime-20261009") if not ok]
    mac_on_linux = [t for ok, t in compare_runs.verify("linux-arm64-ref-1", "mac-runtime-20261009", docs_dir=LINUX) if not ok]
    linux_on_mac = [t for ok, t in compare_runs.verify("baseline", "linux-arm64-ref-2") if not ok]
    assert ok_linux == [] and ok_mac == []
    assert any("[ผลใหม่] runtime ตรงกับ reference (linux-arm64)" in f for f in mac_on_linux)
    assert any("[ผลใหม่] runtime ตรงกับ reference (mac-idntwww)" in f for f in linux_on_mac)


def test_missing_file_is_caught(tmp_path):
    (tmp_path / "oracle_baseline.json").write_text(json.dumps(BASELINE, ensure_ascii=False), encoding="utf-8")
    fails = [t for ok, t in compare_runs.verify("baseline", "nope", out_dir=tmp_path) if not ok]
    assert any("ไม่พบไฟล์ oracle_nope.json" in f for f in fails)


# ---------- ห้ามเขียนทับ ----------

def test_write_new_never_overwrites(tmp_path):
    p = tmp_path / "f.json"
    safe_io.write_new(p, "เดิม")
    with pytest.raises(FileExistsError):
        safe_io.write_new(p, "ใหม่")
    assert p.read_text(encoding="utf-8") == "เดิม"


def test_oracle_refuses_existing_names():
    existing = [p.stem[len("oracle_"):] for p in PRIVATE.glob("oracle_*.json")]
    assert "baseline" in existing
    for name in existing:
        with pytest.raises(FileExistsError):
            oracle.ensure_new(name)
    for bad in ["", "../x", "a/b", " baseline"]:
        with pytest.raises(ValueError):
            oracle.ensure_new(bad)


def test_oracle_cli_does_not_overwrite_baseline():
    target = PRIVATE / "oracle_baseline.json"
    before = (sha(target), target.stat().st_mtime_ns)
    proc = subprocess.run([sys.executable, "-B", str(HERE / "oracle.py"), "baseline"],
                          env=dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1"),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0 and "ไม่เขียนทับ" in proc.stderr
    assert (sha(target), target.stat().st_mtime_ns) == before


def test_fetch_snapshot_refuses_baseline_name_before_network():
    # เรียกเฉพาะตัวตรวจชื่อ ไม่เรียก main() จึงไม่มีทางต่อ Google Sheets
    with pytest.raises(FileExistsError):
        fetch_snapshot.ensure_new("baseline")
    for bad in ["", "../x", "a b"]:
        with pytest.raises(ValueError):
            fetch_snapshot.ensure_new(bad)


def test_baseline_files_are_read_only():
    for name in PROTECTED:
        assert not os.access(PRIVATE / name, os.W_OK), f"{name} ยังเขียนได้"
    for d in (DOCS, DOCS / "linux-arm64"):
        for name in ["baseline_conditions.json", "oracle_baseline_hashes.json", "runtime.json"]:
            assert not os.access(d / name, os.W_OK), f"{d.name}/{name} ยังเขียนได้"


# ---------- ตรึง baseline ----------

def test_freeze_refuses_existing_docs():
    with pytest.raises(FileExistsError):
        freeze_baseline.freeze("baseline")


@pytest.mark.parametrize("breaker", [
    lambda r: r.update(hash_seed="1"),
    lambda r: r["slice_identical"].update({"5": False}),
    lambda r: r.update(instrumentation_neutral=False),
], ids=["hash_seed", "slice", "instrumentation"])
def test_freeze_rejects_run_failing_conditions(tmp_path, monkeypatch, breaker):
    run = copy.deepcopy(BASELINE)
    breaker(run)
    (tmp_path / "oracle_bad.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(freeze_baseline, "OUT", tmp_path)
    monkeypatch.setattr(freeze_baseline, "DOCS", tmp_path / "docs")
    with pytest.raises(ValueError):
        freeze_baseline.freeze("bad")
    assert not (tmp_path / "docs").exists()


# ---------- ตรึง runtime และชุด reference ของ runtime อื่น ----------

def test_freeze_runtime_refuses_existing():
    with pytest.raises(FileExistsError):
        freeze_baseline.freeze_runtime("mac-runtime-20261009")


@pytest.mark.parametrize("breaker, expected", [
    (lambda r: r["output_hashes"].update({"forecast.h5": "0" * 64}), "ผลไม่ตรง"),
    (lambda r: r["source_hashes"].update(_auto_arima_forecast="0" * 64), "source"),
    (lambda r: r.pop("runtime"), "ไม่มีข้อมูล runtime"),
], ids=["outputs", "source", "no_runtime"])
def test_freeze_runtime_rejects_run_not_reproducing_reference(tmp_path, monkeypatch, breaker, expected):
    run = copy.deepcopy(candidate())
    breaker(run)
    (tmp_path / "oracle_bad.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("baseline_conditions.json", "oracle_baseline_hashes.json"):
        shutil.copy(DOCS / name, docs / name)
    monkeypatch.setattr(freeze_baseline, "OUT", tmp_path)
    with pytest.raises(ValueError, match=expected):
        freeze_baseline.freeze_runtime("bad", docs)
    assert not (docs / "runtime.json").exists()


def test_freeze_new_set_writes_three_read_only_files_once(tmp_path, monkeypatch):
    (tmp_path / "oracle_run.json").write_text(json.dumps(candidate(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(freeze_baseline, "OUT", tmp_path)
    docs = tmp_path / "docs" / "some-runtime"
    written = freeze_baseline.freeze("run", docs, "some-runtime")
    assert sorted(p.name for p in written) == ["baseline_conditions.json", "oracle_baseline_hashes.json", "runtime.json"]
    assert all(not os.access(p, os.W_OK) for p in written)
    assert json.loads((docs / "runtime.json").read_text(encoding="utf-8"))["name"] == "some-runtime"
    with pytest.raises(FileExistsError):
        freeze_baseline.freeze("run", docs, "some-runtime")
