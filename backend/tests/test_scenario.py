"""สูตร scenario ของโค้ดใหม่ให้ตัวเลขเดียวกับการ์ดผลกระทบที่หน้าพยากรณ์เดิมแสดง บน runtime เดียวกัน

เทียบกับผลเก็บหน้าจอแบบข้อความ (AppTest) ชุด reference ของ runtime นี้ (ui_conditions.json ของชุด) สถานะ
v07_scenario_<ตัวแปร>_shock<ค่า> ครบ 5 ตัวแปรระยะยาว × 3 ค่า: shock1 = ค่าเริ่มต้นของช่องกรอก (อ่านจาก proto),
shock5_0 = 5.0, shockm2_5 = -2.5 (ui_capture.SHOCKS) ข้อความสูตรในการ์ดยืนยันค่า shock ที่อนุมาน
"""
import hashlib
import json
import re

import ui_compare
from compare_runs import check_runtime

from app.modeling import core, scenario


def reference_states(ref_dir):
    cond = json.loads((ref_dir / "ui_conditions.json").read_text(encoding="utf-8"))
    rt = json.loads((ref_dir / "runtime.json").read_text(encoding="utf-8"))
    name = cond["reference"]["run"]
    manifest_sha = hashlib.sha256((ui_compare.OUT / name / "manifest.json").read_bytes()).hexdigest()
    assert manifest_sha == cond["reference"]["manifest_sha256"], "ชุดหน้าจออ้างอิงไม่ใช่ชุดที่ตรึงไว้"
    manifest, states = ui_compare.load_run(name)
    failed = [t for ok, t in check_runtime(manifest, rt, "อ้างอิง", is_reference=True) if not ok]
    assert not failed, failed
    assert sorted(states) == sorted(cond["states"])
    for state, (sha, _) in states.items():
        assert manifest["captures"][state]["sha256"] == sha, state
    return {state: capture for state, (_, capture) in states.items()}


def strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)
    elif isinstance(obj, str):
        yield obj


def shown(capture, fragment):
    return any(fragment in s for s in strings(capture["elements"]))


def test_scenario_card_matches_reference_screens(computed, ref_dir):
    lr_raw_map = computed["outputs"]["lr_raw_map"]
    states = reference_states(ref_dir)
    checked = []
    for state, capture in states.items():
        m = re.fullmatch(r"v07_scenario_(.+)_shock(.+)", state)
        if not m:
            continue
        var, tag = m.groups()
        box = [e for e in capture["elements"] if e.get("type") == "number_input"
               and e["proto"]["id"].endswith(f"-impact_shock_{var}")]
        assert len(box) == 1, state
        shock = box[0]["proto"]["default"] if tag == "1" else float(tag.replace("m", "-").replace("_", "."))
        coef, p_val = lr_raw_map[var]["coef"], lr_raw_map[var]["p"]
        if var.startswith("ln_"):
            formula = f"{coef:.4f} × {shock:g}%"
        elif var in core._PCT_SCALED_VARS:
            formula = f"(e^({coef:.4f}×{shock:g}/100) − 1) × 100%"
        else:
            formula = f"(e^({coef:.4f}×{shock:g}) − 1) × 100%"
        assert shown(capture, formula), (state, formula)

        pct = scenario.scenario_pct_effect(var, coef, shock)
        color = "var(--green)" if pct >= 0 else "var(--red)"
        arrow = "↑" if pct >= 0 else "↓"
        card = (f'<span style="font-size:1.1rem;color:{color};">{arrow}</span>'
                f'<span style="font-size:1.65rem;font-weight:800;color:{color};line-height:1;">'
                f'{pct:+.2f}%</span>')
        assert shown(capture, card), (state, f"{pct:+.2f}%")
        assert shown(capture, f"p-value = {p_val:.4f}"), state
        checked.append(state)
    assert len(checked) == 15, checked
