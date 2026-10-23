"""Refactor parity (เกณฑ์ A): รันโค้ดที่ย้ายใหม่ใน backend/app ด้วยลำดับการเรียกเดียวกับ oracle ของต้นฉบับ
บน snapshot เดิม แล้วเทียบกับ reference ของ runtime เดียวกันแบบตรงทุกบิต

- เรียก app.modeling.core / app.modeling.tfp / app.data_loader จริง (ไม่เรียกไฟล์แอปต้นฉบับ)
- ปุ่มดึงข้อมูลอ่าน snapshot แทน Google Sheets (แทนเฉพาะ _get_client เหมือน replay ของ oracle)
- ห่อ ARIMA ของ core ด้วยตัวจดเดียวกับ oracle เพื่อเทียบ convergence/คำเตือนของทุก fit
- reference เลือกจาก runtime ปัจจุบันและ hash ของไฟล์ต้นฉบับที่ root (docs/baseline/**/) ถ้าไม่มีชุดที่ตรงจะไม่เทียบ
- ตรวจธงเดียวกับ oracle: พยากรณ์ h สั้นเป็นส่วนต้นของ h15 (slice_identical) และตัวห่อ ARIMA ไม่เปลี่ยนตัวเลข
  ของโค้ดใหม่ (instrumentation_neutral: รัน _auto_arima_forecast h15 ทั้งแบบห่อและไม่ห่อแล้วเทียบ)

    PYTHONHASHSEED=0 python -B -P backend/tests/parity.py <ชื่อผล> [โฟลเดอร์ผล]
    # เขียน <โฟลเดอร์ผล>/candidate_<ชื่อ>.json (ค่าเริ่มต้น private/baseline) + สรุป
"""
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools" / "baseline"
OUT = REPO / "private" / "baseline"
DOCS = REPO / "docs" / "baseline"
for p in (str(REPO / "backend"), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fingerprint  # noqa: E402
import oracle  # noqa: E402
import replay  # noqa: E402
import runtime_info  # noqa: E402
from compare_runs import first_difference  # noqa: E402


def reference_set():
    """ชุด reference ที่ runtime และไฟล์ต้นฉบับที่ root ของ workspace (oracle.file_hashes) ตรงกับปัจจุบัน หรือ None
    — workspace เก็บ reference ของต้นฉบับหลายรุ่น (e6aee03 ที่ docs/baseline/ และ linux-arm64/, 7bf84e4 ที่ 7bf84e4-*/)"""
    rt = runtime_info.comparable(runtime_info.runtime_identity())
    files = {f: hashlib.sha256((REPO / f).read_bytes()).hexdigest() for f in [oracle.APP_FILE, "TFP.py", "data_loader.py"]}
    for d in [DOCS, *sorted(p for p in DOCS.iterdir() if p.is_dir())]:
        f, a = d / "runtime.json", d / "oracle_baseline_hashes.json"
        if f.exists() and a.exists() and json.loads(f.read_text(encoding="utf-8"))["identity"] == rt \
                and json.loads(a.read_text(encoding="utf-8"))["file_hashes"] == files:
            return d
    return None


def compute() -> dict:
    """รันโค้ดใหม่ตามลำดับของ oracle คืนผลดิบ (ยังไม่แปลง) ให้ test อื่นใช้ต่อ"""
    modules_before = set(sys.modules)
    from app import data_loader
    from app.modeling import core, tfp

    tabs = replay.load_tabs()
    real_get_client = data_loader._get_client
    data_loader._get_client = lambda: replay._FakeClient(tabs)
    plain_arima = core.ARIMA
    core.ARIMA = oracle.make_recording_arima(plain_arima)
    oracle.FIT_LOG.clear()
    try:
        df_raw = data_loader.load_data_gsheet()
        active_lr_vars = list(tfp.LONG_RUN_VARS)
        active_sr_spec = list(tfp.SHORT_RUN_SPEC)
        model_df = tfp.build_model_frame(df_raw)
        dep_ln = "ln_" + tfp.DEP_VAR
        lr_res, lr_resid = tfp.run_long_run(model_df, dep_ln, active_lr_vars)
        sr_res = tfp.run_short_run(model_df, dep_ln, active_sr_spec, lr_resid)
        lr_table, sr_table = tfp.build_coefficient_tables(lr_res, sr_res)
        combined_table = core._merge_coefficient_tables(lr_table, sr_table)
        lr_raw_map = core._extract_raw_coefficients(core._unrounded_coefficient_table(lr_res))
        sr_raw_map = core._extract_raw_coefficients(core._unrounded_coefficient_table(sr_res))
        adj_r2 = [tfp.summary_adj_r2(lr_res), tfp.summary_adj_r2(sr_res)]
        diag_table = tfp.run_diagnostics(model_df, dep_ln, active_lr_vars, lr_res, sr_res, lr_resid,
                                         short_run_spec=active_sr_spec)
        diag_display = diag_table.copy()
        diag_display["รายการ"] = diag_display["รายการ"].apply(core.var_label_with_abbr)
        n_fail = int((diag_table["สถานะ"] == "🔴 ไม่ผ่าน").sum())
        n_watch = int(diag_table["สถานะ"].str.startswith("🟡").sum())
        n_pass = int(len(diag_table) - n_fail - n_watch)
        # ตาราง ADF รายตัวแปร (เหมือน oracle: มีเมื่อต้นฉบับ/โค้ดที่ย้ายมีฟังก์ชันนี้ — ตั้งแต่ 7bf84e4)
        extra = {}
        if hasattr(core, "_build_adf_detail_table"):
            extra["adf_detail"] = core._build_adf_detail_table(model_df, dep_ln, active_lr_vars, active_sr_spec)

        tfp_series = model_df[tfp.DEP_VAR].dropna().sort_index()
        forecasts = {h: core._drift_forecast_interval(tfp_series, h) for h in oracle.HORIZONS}
        slice_identical = all(fingerprint.dumps(forecasts[h]) == fingerprint.dumps(forecasts[15].iloc[:h])
                              for h in oracle.HORIZONS)
        fit_groups = {}
        start = len(oracle.FIT_LOG)
        wrapped_h15 = core._auto_arima_forecast(tfp_series, 15)
        fit_groups["neutrality_check_h15"] = oracle.FIT_LOG[start:]
        core.ARIMA = plain_arima
        plain_h15 = core._auto_arima_forecast(tfp_series, 15)
        core.ARIMA = oracle.make_recording_arima(plain_arima)
        instrumentation_neutral = fingerprint.dumps(plain_h15) == fingerprint.dumps(wrapped_h15)
        start = len(oracle.FIT_LOG)
        holdout = core._run_backtest(tfp_series, min_train=oracle.MIN_POINTS_FOR_ARIMA)
        fit_groups["holdout"] = oracle.FIT_LOG[start:]
        start = len(oracle.FIT_LOG)
        rolling = core._run_rolling_backtest(tfp_series, min_train=oracle.MIN_POINTS_FOR_ARIMA, step_ahead=1,
                                             crisis_years=oracle.CRISIS_YEARS)
        fit_groups["rolling"] = oracle.FIT_LOG[start:]
        influence = core._compute_influence_df(model_df, dep_ln, active_lr_vars, lr_raw_map)
    finally:
        core.ARIMA = plain_arima
        data_loader._get_client = real_get_client

    def sample_index(res):
        return [int(i) for i in res.model.data.row_labels]

    outputs = {
        "raw_df": df_raw, "model_df": model_df,
        "lr.params": lr_res.params, "lr.bse": lr_res.bse, "lr.tvalues": lr_res.tvalues,
        "lr.pvalues": lr_res.pvalues, "lr.rsquared": lr_res.rsquared, "lr.nobs": lr_res.nobs,
        "lr.sample_index": sample_index(lr_res), "lr.resid": lr_resid,
        "lr.eg": [lr_res.eg_stat, lr_res.eg_pvalue, list(lr_res.eg_crit)],
        "sr.params": sr_res.params, "sr.bse": sr_res.bse, "sr.tvalues": sr_res.tvalues,
        "sr.pvalues": sr_res.pvalues, "sr.rsquared": sr_res.rsquared, "sr.nobs": sr_res.nobs,
        "sr.sample_index": sample_index(sr_res),
        "adj_r2": adj_r2, "lr_table": lr_table, "sr_table": sr_table, "combined_table": combined_table,
        "lr_raw_map": lr_raw_map, "sr_raw_map": sr_raw_map,
        "diag_table": diag_table, "diag_display": diag_display, "diag_counts": [n_fail, n_watch, n_pass],
        "tfp_series": tfp_series,
        **{f"forecast.h{h}": forecasts[h] for h in oracle.HORIZONS},
        "holdout": holdout, "rolling": rolling, "influence": influence, **extra,
    }
    return {
        "outputs": outputs,
        "fit_groups": fit_groups,
        "flags": {"slice_identical": slice_identical, "instrumentation_neutral": instrumentation_neutral},
        "snapshot_sha256": fingerprint.sha256(tabs),
        "modules_loaded": sorted(set(sys.modules) - modules_before),
        "code_files": {"core": core.__file__, "tfp": tfp.__file__, "data_loader": data_loader.__file__,
                       "config": data_loader.config.__file__},
    }


def run_candidate(computed: dict = None) -> dict:
    """ผลที่เทียบกับ reference ได้ (ตัวเลขเป็น float.hex) พร้อม sha256 ของไฟล์โค้ดใหม่ที่ถูกเรียก"""
    computed = computed or compute()
    return {
        "source_files": {str(Path(f).relative_to(REPO)): hashlib.sha256(Path(f).read_bytes()).hexdigest()
                         for f in computed["code_files"].values()},
        "hash_seed": os.environ.get("PYTHONHASHSEED"),
        "snapshot_sha256": computed["snapshot_sha256"],
        "runtime": runtime_info.runtime_identity(),
        "flags": computed["flags"],
        "outputs": {k: fingerprint.canonical(v) for k, v in computed["outputs"].items()},
        "fit_groups": computed["fit_groups"],
    }


def compare(cand: dict, ref_dir: Path) -> list:
    """คืน [(ผ่านไหม, ข้อความ)] — ตรวจ reference ก่อน แล้วเทียบเนื้อหาทุกค่า"""
    cond = json.loads((ref_dir / "baseline_conditions.json").read_text(encoding="utf-8"))
    anchor = json.loads((ref_dir / "oracle_baseline_hashes.json").read_text(encoding="utf-8"))
    rt = json.loads((ref_dir / "runtime.json").read_text(encoding="utf-8"))
    ref = json.loads((OUT / f"oracle_{anchor['run']}.json").read_text(encoding="utf-8"))
    checks = []
    ref_hashes = {k: fingerprint.sha256_canonical(v) for k, v in ref["outputs"].items()}
    checks.append((ref_hashes == anchor["output_hashes"], f"reference {anchor['run']} ตรงกับ hash ที่ตรึงไว้"))
    checks.append((runtime_info.comparable(cand["runtime"]) == rt["identity"], f"runtime ตรงกับ reference ({rt['name']})"))
    checks.append((cand["hash_seed"] == cond["hash_seed"], "PYTHONHASHSEED = 0"))
    checks.append((cand["snapshot_sha256"] == cond["snapshot_sha256"], "ใช้ snapshot เดียวกับ reference"))
    for flag, want in cond["required_flags"].items():
        checks.append((cand["flags"].get(flag) == want, f"ธง {flag} = {want}"))
    keys = cond["output_keys"]
    missing = sorted(set(keys) - set(cand["outputs"]))
    extra = sorted(set(cand["outputs"]) - set(keys))
    checks.append((not missing and not extra, f"ผลครบ {len(keys)} ค่า" + (f" · ขาด {missing}" if missing else "")
                   + (f" · เกิน {extra}" if extra else "")))
    diffs = []
    for k in keys:
        if k in cand["outputs"]:
            d = first_difference(ref["outputs"][k], cand["outputs"][k])
            if d:
                diffs.append(f"{k} -> {d}")
    checks.append((not diffs and not missing, f"เนื้อหาตรงทุกบิต {len(keys) - len(diffs) - len(missing)}/{len(keys)} ค่า"
                   + "".join(f"\n      ต่าง: {x}" for x in diffs)))
    checks.append((cand["fit_groups"] == ref["fit_groups"], "บันทึก fit ARIMA (converge/คำเตือน) ตรงกัน"))
    return checks


def main(name: str, out_dir: Path = OUT) -> int:
    import safe_io

    if os.environ.get("PYTHONHASHSEED") != "0":
        sys.exit("ต้องรันด้วย PYTHONHASHSEED=0")
    out = Path(out_dir) / f"candidate_{safe_io.check_name(name)}.json"
    safe_io.ensure_absent([out])
    ref_dir = reference_set()
    if ref_dir is None:
        sys.exit("runtime นี้ไม่มีชุด reference ที่ตรึงไว้ — เทียบไม่ได้")
    cand = run_candidate()
    checks = compare(cand, ref_dir)
    safe_io.write_new(out, json.dumps(dict(cand, run=name, reference_set=str(ref_dir.relative_to(REPO)),
                                           checks=[[ok, t] for ok, t in checks]), ensure_ascii=False))
    for ok, text in checks:
        print(("ผ่าน     " if ok else "ไม่ผ่าน  ") + text)
    failed = sum(1 for ok, _ in checks if not ok)
    print(f"\nสรุป: ผ่าน {len(checks) - failed}/{len(checks)} ข้อ · ชุด {ref_dir.relative_to(REPO)} · ผลอยู่ที่ {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("ใช้: parity.py <ชื่อผล> [โฟลเดอร์ผล]")
    sys.exit(main(*sys.argv[1:2], *(Path(a) for a in sys.argv[2:3])))
