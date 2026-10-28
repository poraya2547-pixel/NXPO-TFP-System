"""Runtime migration (B): รายละเอียด ARIMA ใน backtest ของแต่ละ runtime ไว้เทียบข้าม runtime

ไม่ใช่ตัวตัดสิน refactor parity (นั่นคือ compare_runs.py ภายใน runtime เดียวกัน)
- collect: รัน holdout และ rolling ของโค้ดต้นฉบับแบบเดียวกับ oracle แต่ห่อ _auto_arima_forecast
  เพื่อจด order ที่ถูกเลือกทุกครั้ง และจดทุก fit ของ ARIMA (converge/คำเตือน)
  ผลตัวเลขต้องตรง reference ของ runtime นี้ทุกบิต (พิสูจน์ว่าการจดไม่เปลี่ยนตัวเลข) ไม่งั้นหยุด
- report: เทียบสองผล collect (คนละ runtime) พิมพ์ markdown: order ที่ต่าง, convergence/คำเตือนที่ต่าง,
  ค่าทายที่ต่าง และค่าที่แสดงบนหน้าจอที่ต่าง (รูปแบบเดียวกับแอป: MAPE .2f, RMSE .3f, DM .3f, ตาราง .2f)

    PYTHONHASHSEED=0 python -B tools/baseline/runtime_diff.py collect <ชื่อ>
    python -B tools/baseline/runtime_diff.py report <ชื่อ runtime ก> <ชื่อ runtime ข>
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "private" / "baseline"
DOCS = REPO / "docs" / "baseline"
sys.path[:0] = [str(REPO), str(HERE)]
import safe_io  # noqa: E402


def _reference_for(runtime: dict):
    """หาชุด reference ที่ runtime ตรงกัน (docs/baseline หรือโฟลเดอร์ย่อย)"""
    import runtime_info

    for d in [DOCS, *sorted(p for p in DOCS.iterdir() if p.is_dir())]:
        rt = d / "runtime.json"
        if rt.exists() and json.loads(rt.read_text(encoding="utf-8"))["identity"] == runtime_info.comparable(runtime):
            return d
    return None


def collect(name: str) -> Path:
    import warnings

    import numpy as np
    import pandas as pd
    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.stattools import adfuller

    import fingerprint
    import oracle
    import replay
    import runtime_info
    import TFP

    out = OUT / f"runtime_diff_{safe_io.check_name(name)}.json"
    safe_io.ensure_absent([out])
    warnings.simplefilter("ignore", ConvergenceWarning)
    warnings.simplefilter("ignore", UserWarning)
    ns = {"np": np, "pd": pd, "re": __import__("re"), "math": __import__("math"), "warnings": warnings,
          "adfuller": adfuller, "ConvergenceWarning": ConvergenceWarning,
          "ARIMA": oracle.make_recording_arima(ARIMA)}
    ns.update({n: getattr(TFP, n) for n in oracle.TFP_NAMES_IMPORTED_BY_APP})
    oracle.extract_app_functions(ns)

    original, calls, context = ns["_auto_arima_forecast"], [], {"name": ""}

    def recording_forecast(train, h, *args, **kwargs):
        start = len(oracle.FIT_LOG)
        fc_df, order = original(train, h, *args, **kwargs)
        calls.append({"context": context["name"], "train_start": int(train.index.min()),
                      "train_end": int(train.index.max()), "n_train": int(len(train)), "h": int(h),
                      "kwargs": kwargs, "order": list(order), "fits": oracle.FIT_LOG[start:]})
        return fc_df, order

    ns["_auto_arima_forecast"] = recording_forecast
    model_df = TFP.build_model_frame(replay.load_df_from_snapshot())
    tfp_series = model_df[TFP.DEP_VAR].dropna().sort_index()
    context["name"] = "holdout"
    holdout = ns["_run_backtest"](tfp_series, min_train=oracle.MIN_POINTS_FOR_ARIMA)
    context["name"] = "rolling"
    rolling = ns["_run_rolling_backtest"](tfp_series, min_train=oracle.MIN_POINTS_FOR_ARIMA, step_ahead=1,
                                          crisis_years=oracle.CRISIS_YEARS)

    runtime = runtime_info.runtime_identity()
    ref_dir = _reference_for(runtime)
    if ref_dir is None:
        raise RuntimeError("runtime นี้ไม่มีชุด reference ที่ตรึงไว้ เทียบไม่ได้")
    anchor = json.loads((ref_dir / "oracle_baseline_hashes.json").read_text(encoding="utf-8"))
    outputs = {"holdout": holdout, "rolling": rolling}
    hashes = {k: fingerprint.sha256(v) for k, v in outputs.items()}
    if any(hashes[k] != anchor["output_hashes"][k] for k in hashes):
        raise RuntimeError("ผล holdout/rolling ไม่ตรง reference ของ runtime นี้ — การจดอาจเปลี่ยนตัวเลข หยุด")
    safe_io.write_new(out, json.dumps({
        "run": name, "hash_seed": os.environ.get("PYTHONHASHSEED"), "runtime": runtime,
        "reference_set": ref_dir.name if ref_dir != DOCS else "mac-idntwww",
        "outputs": {k: fingerprint.canonical(v) for k, v in outputs.items()}, "output_hashes": hashes,
        "calls": calls,
    }, ensure_ascii=False))
    out.chmod(0o444)
    return out


def _dec(v):
    if isinstance(v, str) and v.startswith(("0x", "-0x")):
        return float.fromhex(v)
    if isinstance(v, dict) and v.get("__type__") == "dict":
        return {k: _dec(x) for k, x in v["items"]}
    if isinstance(v, dict) and v.get("__type__") == "tuple":
        return [_dec(x) for x in v["items"]]
    return v


def _frame(canon):
    return [dict(zip(canon["columns"], [_dec(x) for x in row])) | {"_index": i}
            for i, row in zip(canon["index"], canon["values"])]


def report(a_name: str, b_name: str) -> str:
    a = json.loads((OUT / f"runtime_diff_{safe_io.check_name(a_name)}.json").read_text(encoding="utf-8"))
    b = json.loads((OUT / f"runtime_diff_{safe_io.check_name(b_name)}.json").read_text(encoding="utf-8"))
    la, lb = a["reference_set"], b["reference_set"]
    lines = [f"เทียบ `{a_name}` ({la}) กับ `{b_name}` ({lb}) — ทั้งสองผลตรง reference ของ runtime ตัวเองทุกบิตแล้ว", ""]

    # 1) order ที่ถูกเลือกและ convergence ต่อการเรียก
    key = lambda c: (c["context"], c["train_end"], c["h"])  # noqa: E731
    ca, cb = {key(c): c for c in a["calls"]}, {key(c): c for c in b["calls"]}
    order_diff, fit_diff = [], []
    for k in sorted(set(ca) | set(cb)):
        x, y = ca.get(k), cb.get(k)
        if x is None or y is None:
            order_diff.append(f"| {k[0]} | {k[1]} | มีแค่ฝั่งเดียว | |")
            continue
        if x["order"] != y["order"]:
            order_diff.append(f"| {k[0]} | ปีสุดท้ายที่ฝึก {k[1]} (n={x['n_train']}) | {tuple(x['order'])} | {tuple(y['order'])} |")
        nca = sum(1 for f in x["fits"] if f.get("converged") is False)
        ncb = sum(1 for f in y["fits"] if f.get("converged") is False)
        wa = sorted({w for f in x["fits"] for w in f.get("warnings", [])})
        wb = sorted({w for f in y["fits"] for w in f.get("warnings", [])})
        sel_a = [f for f in x["fits"] if f.get("order") == x["order"]][-1:]
        sel_b = [f for f in y["fits"] if f.get("order") == y["order"]][-1:]
        conv_a = sel_a[0].get("converged") if sel_a else None
        conv_b = sel_b[0].get("converged") if sel_b else None
        if (nca, wa, conv_a) != (ncb, wb, conv_b):
            fit_diff.append(f"| {k[0]} | {k[1]} | {nca}/{len(x['fits'])} · ตัวที่เลือก converge={conv_a} | "
                            f"{ncb}/{len(y['fits'])} · ตัวที่เลือก converge={conv_b} |"
                            + (" คำเตือนต่างกัน |" if wa != wb else " |"))
    n_calls = len(set(ca) | set(cb))
    lines += [f"### order ที่ ARIMA เลือก (ต่าง {len(order_diff)} จาก {n_calls} ครั้ง)", "",
              f"| ส่วน | หน้าต่าง | {la} | {lb} |", "|---|---|---|---|", *order_diff, ""]
    lines += [f"### convergence และคำเตือนของ fit (ต่าง {len(fit_diff)} จาก {n_calls} ครั้ง)", "",
              f"| ส่วน | ปีสุดท้ายที่ฝึก | {la}: fit ไม่ converge · ตัวที่เลือก | {lb} | หมายเหตุ |",
              "|---|---|---|---|---|", *fit_diff, ""]

    # 2) ค่าทายและค่าที่แสดง
    for part, label_col in (("holdout", "_index"), ("rolling", "ปีที่ทาย")):
        fa, fb = _frame(a["outputs"][part]["items"][0]), _frame(b["outputs"][part]["items"][0])
        raw, shown = 0, []
        for ra, rb in zip(fa, fb):
            for col in ("ARIMA", "Naive", "Drift"):
                if ra[col] != rb[col]:
                    raw += 1
                    if f"{ra[col]:.2f}" != f"{rb[col]:.2f}":
                        shown.append(f"| {part} | {ra[label_col]} | {col} | {ra[col]:.2f} | {rb[col]:.2f} |")
        lines += [f"### ค่าทายใน {part}: ต่าง {raw} ค่า · ต่างที่ทศนิยม 2 ตำแหน่ง (ที่ตารางแสดง) {len(shown)} ค่า", ""]
        if shown:
            lines += [f"| ส่วน | ปี | โมเดล | {la} | {lb} |", "|---|---|---|---|---|", *shown]
        lines.append("")

    # 3) ตัวเลขสรุป ตามรูปแบบที่หน้าเว็บแสดง
    rows = []
    for part in ("holdout", "rolling"):
        ma, mb = _dec(a["outputs"][part]["items"][1]), _dec(b["outputs"][part]["items"][1])
        for k in sorted(set(ma) | set(mb)):
            x, y = ma.get(k), mb.get(k)
            if x == y:
                continue
            if isinstance(x, dict):
                for kk in sorted(x):
                    if x[kk] != y.get(kk):
                        fmt = "{:.3f}" if kk in ("stat", "pvalue") else "{}"
                        rows.append(f"| {part} | {k}.{kk} | {fmt.format(x[kk])} | {fmt.format(y.get(kk))} | {x[kk]!r} / {y.get(kk)!r} |")
            elif isinstance(x, float):
                fmt = "{:.3f}" if k.endswith("rmse") else "{:.2f}"
                rows.append(f"| {part} | {k} | {fmt.format(x)} | {fmt.format(y)} | {x!r} / {y!r} |")
            else:
                rows.append(f"| {part} | {k} | {x} | {y} | |")
    lines += ["### ตัวเลขสรุปที่ต่าง (ค่าที่แสดง · ค่าดิบ)", "",
              f"| ส่วน | รายการ | {la} | {lb} | ค่าดิบ |", "|---|---|---|---|---|", *rows, ""]
    return "\n".join(lines)


def _leaves(obj, path="$"):
    if isinstance(obj, dict):
        for k in sorted(obj):
            yield from _leaves(obj[k], f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def _snippet(a: str, b: str, width: int = 50):
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    s = max(0, i - width)
    return a[s:i + width].replace("\n", " "), b[s:i + width].replace("\n", " ")


def ui_report(a_run: str, b_run: str) -> str:
    """ไล่ทุกจุดที่ต่างระหว่างหน้าจอสองชุด (คนละ runtime) แยกข้อความที่แสดงกับข้อมูลตาราง/กราฟ"""
    import ui_compare

    cond = json.loads(ui_compare.CONDITIONS.read_text(encoding="utf-8"))
    _, sa = ui_compare.load_run(a_run)
    _, sb = ui_compare.load_run(b_run)
    texts, data, states_diff = {}, {}, []
    for state in cond["states"]:
        la = dict(_leaves(ui_compare.without_path_hash(sa[state][1])))
        lb = dict(_leaves(ui_compare.without_path_hash(sb[state][1])))
        diffs = [p for p in sorted(set(la) | set(lb)) if la.get(p) != lb.get(p)]
        if not diffs:
            continue
        states_diff.append(state)
        for p in diffs:
            x, y = la.get(p), lb.get(p)
            elem = p.split("]")[0] + "]"
            if isinstance(x, str) and isinstance(y, str) and ".arrow." not in p:
                texts.setdefault(_snippet(x, y), []).append(state)
            else:
                data.setdefault(elem, {"n": 0, "states": set(), "example": (p, x, y)})
                data[elem]["n"] += 1
                data[elem]["states"].add(state)
    lines = [f"หน้าจอที่ต่าง {len(states_diff)} จาก {len(cond['states'])} สถานะ: {', '.join(states_diff)}", "",
             f"### ข้อความที่แสดงต่างกัน ({len(texts)} แบบ ไม่นับซ้ำข้ามสถานะ)", "",
             f"| ตัวอย่างสถานะ | {a_run} | {b_run} |", "|---|---|---|"]
    for (x, y), sts in sorted(texts.items(), key=lambda kv: kv[1][0]):
        lines.append(f"| {sts[0]} (+{len(sts) - 1}) | `{x}` | `{y}` |")
    lines += ["", f"### ข้อมูลตาราง/กราฟที่ต่าง (Arrow ที่หน้าเว็บนำไปแสดง)", "",
              "| องค์ประกอบ | จำนวนค่าที่ต่าง (รวมทุกสถานะ) | จำนวนสถานะ | ตัวอย่าง |", "|---|---|---|---|"]
    for elem, d in sorted(data.items()):
        p, x, y = d["example"]
        lines.append(f"| `{elem}` | {d['n']} | {len(d['states'])} | `{p.split('arrow.')[-1][:60]}`: {x!r} → {y!r} |")
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        if len(args) == 3 and args[0] == "ui-report":
            print(ui_report(args[1], args[2]))
        elif len(args) == 2 and args[0] == "collect":
            if os.environ.get("PYTHONHASHSEED") != "0":
                sys.exit("ต้องรันด้วย PYTHONHASHSEED=0")
            print(collect(args[1]))
        elif len(args) == 3 and args[0] == "report":
            print(report(args[1], args[2]))
        else:
            sys.exit("ใช้: runtime_diff.py collect <ชื่อ> | report <ชื่อ ก> <ชื่อ ข>")
    except (FileExistsError, ValueError, RuntimeError) as e:
        sys.exit(f"หยุด: {e}")
