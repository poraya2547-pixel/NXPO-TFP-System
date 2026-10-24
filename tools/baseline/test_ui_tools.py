"""ทดสอบว่าตัวเทียบหน้าจอ (ui_compare) ตรวจตกเมื่อผลผิด, ui_capture ไม่ทับชุดเดิม และ log แยกจริง

ไม่รันแอปใหม่ ไม่อ่านชีต: คัดลอกชุด ui-baseline ไป tmp แล้วแก้ทีละจุด

    /opt/anaconda3/envs/idntwww/bin/python -B -m pytest -p no:cacheprovider -q tools/baseline/test_ui_tools.py
"""
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
UI = REPO / "private" / "baseline" / "ui"
sys.path.insert(0, str(HERE))
import freeze_baseline  # noqa: E402
import ui_compare  # noqa: E402

COND = json.loads(ui_compare.CONDITIONS.read_text(encoding="utf-8"))
RUNTIME = json.loads((ui_compare.CONDITIONS.parent / "runtime.json").read_text(encoding="utf-8"))
LINUX_SET = ui_compare.CONDITIONS.parent / "linux-arm64" / "ui_conditions.json"
N_STATES = len(COND["states"])
STATE = "v07_scenario_ln_HDI_shock5_0"
LOGIN = "r02_login_form"


@pytest.fixture
def runs(tmp_path):
    """ref = สำเนา ui-baseline ตรง ๆ · cand = สำเนาเดียวกันที่ใส่ runtime ของชุด Mac (เหมือนรันใน runtime นั้น)"""
    for name in ("ref", "cand"):
        shutil.copytree(UI / "ui-baseline", tmp_path / name)
        for p in [tmp_path / name, *(tmp_path / name).iterdir()]:
            os.chmod(p, 0o755 if p.is_dir() else 0o644)
    edit_manifest(tmp_path, "cand", lambda m: m.update(runtime=dict(RUNTIME["identity"], declared_image=None)))
    return tmp_path


def failures(tmp_path):
    return [t for ok, t in ui_compare.verify("ref", "cand", out_dir=tmp_path) if not ok]


def edit_manifest(tmp_path, run, mutate):
    mpath = tmp_path / run / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    mutate(manifest)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def rewrite(tmp_path, state, mutate, update_manifest=True, run="cand"):
    path = tmp_path / run / f"{state}.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    mutate(capture)
    text = json.dumps(capture, ensure_ascii=False, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    if update_manifest:
        edit_manifest(tmp_path, run, lambda m: m["captures"][state].update(
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()))


def drop_state(tmp_path, run, state):
    (tmp_path / run / f"{state}.json").unlink()
    edit_manifest(tmp_path, run, lambda m: m["captures"].pop(state))


def change_shown_percent(capture):
    """เปลี่ยนตัวเลข % ที่แสดงในการ์ดผลกระทบ (+5.60% -> +5.61%)"""
    for e in capture["elements"]:
        body = (e.get("proto") or {}).get("body")
        if isinstance(body, str) and "+5.60%" in body:
            e["proto"]["body"] = body.replace("+5.60%", "+5.61%")
            return
    raise AssertionError("ไม่พบ +5.60% ในสถานะนี้")


# ---------- ชุดถูกต้อง ----------

def test_identical_copy_passes(runs):
    assert failures(runs) == []


REAL = ["ui-mac-runtime-20261009", "ui-linux-arm64-ref-1", "ui-linux-arm64-ref-2"]


@pytest.mark.skipif(not all((UI / n / "manifest.json").exists() for n in REAL), reason="ยังไม่มีชุดจริงของแต่ละ runtime")
def test_real_captures_per_runtime():
    """ชุดจริง: รอบใหม่ใน runtime เดียวกันผ่าน และข้าม runtime ต้องตกที่ runtime"""
    assert [t for ok, t in ui_compare.verify("ui-baseline", "ui-mac-runtime-20261009") if not ok] == []
    assert [t for ok, t in ui_compare.verify("ui-linux-arm64-ref-1", "ui-linux-arm64-ref-2", conditions=LINUX_SET) if not ok] == []
    cross = [t for ok, t in ui_compare.verify("ui-baseline", "ui-linux-arm64-ref-2") if not ok]
    assert any("[ชุดใหม่] runtime ตรงกับ reference (mac-idntwww)" in f for f in cross)
    cross2 = [t for ok, t in ui_compare.verify("ui-linux-arm64-ref-1", "ui-mac-runtime-20261009", conditions=LINUX_SET) if not ok]
    assert any("[ชุดใหม่] runtime ตรงกับ reference (linux-arm64)" in f for f in cross2)


def test_capture_without_runtime_is_caught(runs):
    edit_manifest(runs, "cand", lambda m: m.pop("runtime"))
    assert any("[ชุดใหม่] ไม่มีข้อมูล runtime" in f for f in failures(runs))


def test_capture_from_other_runtime_is_caught(runs):
    edit_manifest(runs, "cand", lambda m: m["runtime"].update(machine="aarch64", system="Linux"))
    assert any("[ชุดใหม่] runtime ตรงกับ reference" in f and "machine" in f for f in failures(runs))


# ---------- เนื้อหาผิด ----------

def test_changed_number_is_caught_even_if_manifest_updated(runs):
    rewrite(runs, STATE, change_shown_percent)
    assert any(f"เนื้อหาตรงกัน {N_STATES - 1}/{N_STATES}" in f and STATE in f for f in failures(runs))


def test_changed_number_with_stale_manifest_is_caught(runs):
    rewrite(runs, STATE, change_shown_percent, update_manifest=False)
    fails = failures(runs)
    assert any("hash ใน manifest ตรงกับไฟล์" in f for f in fails)
    assert any(f"เนื้อหาตรงกัน {N_STATES - 1}/{N_STATES}" in f for f in fails)


def set_widget_id(capture, old_key, new_id_part):
    for e in capture["elements"]:
        wid = (e.get("proto") or {}).get("id", "")
        if wid.endswith(f"-{old_key}"):
            e["proto"]["id"] = new_id_part(wid)
            return
    raise AssertionError(f"ไม่พบ widget {old_key}")


def test_path_derived_widget_hash_is_ignored(runs):
    state = "v03_forecast_h5_default"
    rewrite(runs, state, lambda c: set_widget_id(
        c, "tfp_forecast_horizon", lambda w: "$$ID-" + "0" * 32 + "-tfp_forecast_horizon"))
    assert failures(runs) == []


def test_widget_key_change_is_caught(runs):
    state = "v03_forecast_h5_default"
    rewrite(runs, state, lambda c: set_widget_id(
        c, "tfp_forecast_horizon", lambda w: w.replace("-tfp_forecast_horizon", "-other_key")))
    assert any(f"เนื้อหาตรงกัน {N_STATES - 1}/{N_STATES}" in f and state in f for f in failures(runs))


def test_exception_is_caught(runs):
    rewrite(runs, STATE, lambda c: c["exceptions"].append("KeyError: 'x'"))
    assert any("ไม่มี exception" in f for f in failures(runs))


# ---------- ความครบตามรายชื่อที่ตรึงไว้ ----------

def test_missing_state_is_caught(runs):
    drop_state(runs, "cand", STATE)
    assert any("[ชุดใหม่] สถานะครบ" in f and "ขาด" in f and STATE in f for f in failures(runs))


def test_two_empty_sets_fail(runs):
    for run in ("ref", "cand"):
        for p in (runs / run).glob("*.json"):
            if p.name != "manifest.json":
                p.unlink()
        edit_manifest(runs, run, lambda m: m.update(captures={}))
    fails = failures(runs)
    assert any("[อ้างอิง] สถานะครบ" in f for f in fails)
    assert any("[ชุดใหม่] สถานะครบ" in f for f in fails)
    assert any("เนื้อหาตรงกัน 0/" in f for f in fails)


def test_both_missing_login_form_fail(runs):
    for run in ("ref", "cand"):
        drop_state(runs, run, LOGIN)
    fails = failures(runs)
    assert any("[อ้างอิง] สถานะครบ" in f and LOGIN in f for f in fails)
    assert any("[ชุดใหม่] สถานะครบ" in f and LOGIN in f for f in fails)


def test_listed_state_without_file_is_caught(runs):
    (runs / "cand" / f"{LOGIN}.json").unlink()  # manifest ยังอ้างถึง แต่ไฟล์หาย
    assert any("[ชุดใหม่] สถานะครบ" in f and LOGIN in f for f in failures(runs))


def test_extra_state_is_caught(runs):
    shutil.copy(runs / "cand" / f"{STATE}.json", runs / "cand" / "zz_extra.json")
    edit_manifest(runs, "cand", lambda m: m["captures"].update(zz_extra=dict(m["captures"][STATE])))
    assert any("เกิน ['zz_extra']" in f for f in failures(runs))


# ---------- metadata และชุดอ้างอิง ----------

@pytest.mark.parametrize("mutate, expected", [
    (lambda m: m.update(hash_seed=None), "PYTHONHASHSEED"),
    (lambda m: m.pop("hash_seed"), "PYTHONHASHSEED"),
    (lambda m: m.pop("fetch_log_sha256"), "fetch_log"),
    (lambda m: m.update(fetch_log_sha256="0" * 64), "fetch_log"),
    (lambda m: m.pop("fixed_loaded_at"), "เวลาที่ใช้แทนการกดดึงข้อมูล"),
    (lambda m: m.update(fixed_loaded_at="2026-10-09T00:00:00"), "เวลาที่ใช้แทนการกดดึงข้อมูล"),
], ids=["seed_none", "seed_missing", "log_missing", "log_other", "time_missing", "time_other"])
def test_bad_metadata_is_caught(runs, mutate, expected):
    edit_manifest(runs, "cand", mutate)
    assert any("[ชุดใหม่]" in f and expected in f for f in failures(runs))


def test_tampered_reference_with_updated_hash_is_caught(runs):
    rewrite(runs, STATE, change_shown_percent, run="ref")
    rewrite(runs, STATE, change_shown_percent, run="cand")  # ทั้งคู่ตรงกันเอง แต่ไม่ใช่ชุดที่ตรึงไว้
    assert any("[อ้างอิง] เป็นชุดที่ตรึงไว้" in f for f in failures(runs))


# ---------- ห้ามเขียนทับ ----------

def test_capture_refuses_existing_name():
    target = UI / "ui-baseline" / "manifest.json"
    before = (hashlib.sha256(target.read_bytes()).hexdigest(), target.stat().st_mtime_ns)
    proc = subprocess.run([sys.executable, "-B", str(HERE / "ui_capture.py"), "ui-baseline"],
                          env=dict(os.environ, PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1"),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0 and "ไม่เขียนทับ" in proc.stderr
    assert (hashlib.sha256(target.read_bytes()).hexdigest(), target.stat().st_mtime_ns) == before


def test_ui_baseline_and_conditions_are_read_only():
    assert not os.access(UI / "ui-baseline", os.W_OK)
    assert not any(os.access(p, os.W_OK) for p in (UI / "ui-baseline").iterdir())
    assert not os.access(ui_compare.CONDITIONS, os.W_OK)


def test_freeze_ui_refuses_existing_conditions():
    with pytest.raises(FileExistsError):
        freeze_baseline.freeze_ui("ui-baseline")


@pytest.mark.parametrize("breaker", [
    lambda d: edit_manifest(d.parent, d.name, lambda m: m.update(hash_seed=None)),
    lambda d: edit_manifest(d.parent, d.name, lambda m: m.update(captures={})),
    lambda d: edit_manifest(d.parent, d.name, lambda m: m["captures"][STATE].update(exceptions=1)),
    lambda d: (d / f"{STATE}.json").unlink(),
], ids=["seed", "empty", "exception", "missing_file"])
def test_freeze_ui_rejects_bad_set(runs, monkeypatch, breaker):
    breaker(runs / "cand")
    monkeypatch.setattr(freeze_baseline, "UI_OUT", runs)
    monkeypatch.setattr(freeze_baseline, "DOCS", runs / "docs")
    with pytest.raises(ValueError):
        freeze_baseline.freeze_ui("cand")
    assert not (runs / "docs").exists()


# ---------- log ทดสอบแยกจาก workspace ----------

def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_stage_uses_original_app_and_baseline_log(tmp_path):
    import stage

    s = stage.make_stage(tmp_path / "s")
    assert (s / stage.APP_FILE).resolve() == stage.REPO / stage.APP_FILE
    assert (s / "fonts").resolve() == stage.REPO / "fonts"
    pngs = sorted(p.name for p in stage.REPO.glob("*.png"))
    assert pngs and all((s / n).resolve() == stage.REPO / n for n in pngs)
    assert sha_file(s / "fetch_log.csv") == sha_file(stage.BASELINE_LOG) == COND["fetch_log_sha256"]
    assert os.access(s / "fetch_log.csv", os.W_OK)  # แอปเขียนต่อท้ายได้ โดยไม่แตะไฟล์ baseline


def test_stage_refuses_reuse(tmp_path):
    import stage

    stage.make_stage(tmp_path / "s")
    with pytest.raises(FileExistsError):
        stage.make_stage(tmp_path / "s")


def test_run_app_refuses_without_stage():
    env = {k: v for k, v in os.environ.items() if k != "TFP_STAGE"}
    proc = subprocess.run([sys.executable, "-B", str(HERE / "run_app_snapshot.py")],
                          env=dict(env, PYTHONDONTWRITEBYTECODE="1"), capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0 and "TFP_STAGE" in proc.stderr


def test_logs_are_read_only():
    logs = REPO / "private" / "baseline" / "logs"
    assert not any(os.access(p, os.W_OK) for p in logs.iterdir())


def test_freeze_ui_rejects_runtime_not_matching_set(runs, monkeypatch):
    edit_manifest(runs, "cand", lambda m: m["runtime"].update(machine="x86_64"))
    docs = runs / "docs"
    docs.mkdir()
    shutil.copy(ui_compare.CONDITIONS.parent / "runtime.json", docs / "runtime.json")
    monkeypatch.setattr(freeze_baseline, "UI_OUT", runs)
    with pytest.raises(ValueError, match="runtime"):
        freeze_baseline.freeze_ui("cand", docs)
    assert not (docs / "ui_conditions.json").exists()
