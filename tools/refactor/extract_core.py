"""Step 2: สร้างไฟล์ backend จากโค้ดต้นฉบับที่ root ของ workspace แบบคัดลอกทั้งก้อน (ห้ามทับไฟล์ที่มีอยู่)
ต้นฉบับ: e6aee03 (Step 2, 9 ต.ค.) → acc64ee (10 ต.ค. — เพิ่ม _TREND_LABEL/_build_adf_detail_table, VARIABLE_LABELS เปลี่ยน)
      → 4c8aa71 (20 ต.ค. — ARIMA เลือกโมเดลด้วย Ljung-Box, ช่วง drift T−1, backtest max_windows, influence)

- backend/app/modeling/tfp.py   = TFP.py ทุก byte
- backend/app/modeling/core.py  = ฟังก์ชัน/ค่าคงที่คำนวณจาก TFP_App1.3.0.py ตามลำดับเดิม
                                  เปลี่ยนเพียง: ถอด @st.cache_data(show_spinner=False) ของ _auto_arima_forecast
                                  (และ _run_backtest/_run_rolling_backtest ตั้งแต่ 4c8aa71)
- backend/app/charts.py         = ตัวสร้างกราฟ Altair 3 ตัว เปลี่ยนเพียง: ไม่วางกราฟลงหน้า Streamlit แต่คืนค่า
                                  (_nice_line_chart คืน chart, _nice_line_chart_with_forecast คืน (chart, HTML คำอธิบายเดิม))
ไม่แก้เนื้อการคำนวณ ทุกการเปลี่ยนถูกตรวจซ้ำด้วย backend/tests/test_moved_source.py

    /opt/anaconda3/envs/idntwww/bin/python -B tools/refactor/extract_core.py
"""
import ast
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "TFP_App1.3.0.py"
sys.path.insert(0, str(REPO / "tools" / "baseline"))
import safe_io  # noqa: E402

SOURCE_COMMIT = "4c8aa71"  # ต้นฉบับที่ root ของ workspace (ใช้ในหัวไฟล์/คอมเมนต์ที่สร้าง)

CORE = ["VARIABLE_ORDER", "VARIABLE_LABELS", "var_label_with_abbr", "_var_full_name", "_VAR_CODE_RE",
        "_parse_variable_code", "_significance_stars", "_format_coefficient_cell", "_unrounded_coefficient_table",
        "_extract_raw_coefficients", "_merge_coefficient_tables", "_auto_arima_forecast", "_drift_forecast",
        "_drift_forecast_interval", "_diebold_mariano", "_dm_verdict", "_MODEL_COLORS", "_PCT_SCALED_VARS",
        "_MODEL_LABELS", "_run_backtest", "_run_rolling_backtest", "_compute_influence_df",
        "_TREND_LABEL", "_build_adf_detail_table", "_fmt3"]  # สองชื่อหลังมีตั้งแต่ acc64ee (worker คำนวณตาราง ADF)
CHARTS = ["FONT_FAMILY", "_nice_line_chart", "_mape_threshold_chart", "_nice_line_chart_with_forecast"]
DECORATOR = "@st.cache_data(show_spinner=False)\n"
# ฟังก์ชันที่ต้นฉบับห่อด้วย st.cache_data (มีผลแค่ cache ของ Streamlit) — 4c8aa71 เพิ่ม _run_backtest/_run_rolling_backtest
CACHED = {"_auto_arima_forecast", "_run_backtest", "_run_rolling_backtest"}
ALTAIR_CALL = "    st.altair_chart(chart, use_container_width=True)\n"


def top_level(src: str) -> dict:
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = node
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in out:
                raise RuntimeError(f"{node.targets[0].id} ถูกกำหนดค่าหลายครั้ง")
            out[node.targets[0].id] = node
    return out


def segment(src: str, node) -> str:
    lines = src.splitlines(keepends=True)
    first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return "".join(lines[first - 1:node.end_lineno])


def build(names, src, nodes, transform) -> str:
    parts = []
    for name in sorted(names, key=lambda n: nodes[n].lineno):
        node = nodes[name]
        text = transform(name, segment(src, node))
        parts.append(f"# ย้ายจาก TFP_App1.3.0.py:{node.lineno}-{node.end_lineno} ({SOURCE_COMMIT})\n{text}")
    return "\n\n".join(parts)


def core_transform(name, text):
    if name in CACHED:
        if not text.startswith(DECORATOR):
            raise RuntimeError(f"decorator ของ {name} ไม่ตรงที่คาด")
        return text[len(DECORATOR):]
    if text.lstrip().startswith("@"):
        raise RuntimeError(f"{name} มี decorator ที่ไม่ได้คาดไว้")
    return text


def chart_transform(name, text):
    if name == "_nice_line_chart":
        if text.count(ALTAIR_CALL) != 1 or not text.endswith(ALTAIR_CALL):
            raise RuntimeError("_nice_line_chart ไม่ได้จบด้วย st.altair_chart ตามที่คาด")
        return text[: -len(ALTAIR_CALL)] + "    return chart\n"
    if name == "_nice_line_chart_with_forecast":
        if text.count(ALTAIR_CALL) != 1:
            raise RuntimeError("_nice_line_chart_with_forecast: st.altair_chart ไม่ตรงที่คาด")
        text = text.replace(ALTAIR_CALL, "")
        head, sep, tail = text.rpartition("    st.markdown(\n")
        if not sep or not tail.endswith("        unsafe_allow_html=True,\n    )\n"):
            raise RuntimeError("_nice_line_chart_with_forecast: st.markdown ท้ายฟังก์ชันไม่ตรงที่คาด")
        body = tail[: -len("        unsafe_allow_html=True,\n    )\n")]
        if not body.endswith("',\n"):
            raise RuntimeError("_nice_line_chart_with_forecast: argument แรกของ st.markdown ไม่ได้จบด้วย ',")
        # ตัดคอมมาท้าย argument ออก ไม่งั้น legend_html จะกลายเป็น tuple แทน string
        return head + "    legend_html = (\n" + body[:-2] + "\n    )\n    return chart, legend_html\n"
    return text


CORE_HEAD = '''"""ฟังก์ชันคำนวณที่ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit 4c8aa71)

คัดลอกทั้งก้อนตามลำดับเดิมด้วย tools/refactor/extract_core.py ห้ามแก้เนื้อการคำนวณ
ต่างจากต้นฉบับเพียง: ถอด @st.cache_data(show_spinner=False) ของ _auto_arima_forecast, _run_backtest, _run_rolling_backtest (มีผลแค่ cache)
ตรวจด้วย backend/tests/test_moved_source.py (โครงสร้างโค้ด) และ test_parity_core.py (ตัวเลขตรงทุกบิต)
"""
import math
import re
import warnings
from typing import Optional  # 4c8aa71: annotation ของ _run_rolling_backtest (แอปเดิม :89)

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller
from statsmodels.tools.sm_exceptions import ConvergenceWarning

# ชื่อจาก TFP.py ที่ _build_adf_detail_table ใช้ (แอปเดิม import จาก TFP — TFP_App1.3.0.py:81-86 ของ acc64ee)
from .tfp import ADF_DIFF_TREND, adf_report, CANDIDATE_VARS

# ตั้งค่า warnings แบบเดียวกับหัวไฟล์แอปเดิม (TFP_App1.3.0.py:56-57) — มีผลแค่การแสดงคำเตือน
warnings.simplefilter("ignore", ConvergenceWarning)
warnings.simplefilter("ignore", UserWarning)


'''

CHARTS_HEAD = '''"""ตัวสร้างกราฟ Altair ที่ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit 4c8aa71)

คัดลอกทั้งก้อนด้วย tools/refactor/extract_core.py ต่างจากต้นฉบับเพียงไม่วางกราฟลงหน้า Streamlit:
_nice_line_chart คืน chart และ _nice_line_chart_with_forecast คืน (chart, HTML คำอธิบายกราฟเดิม)
หน้าเว็บใหม่นำ chart.to_dict() (Vega-Lite) ไปแสดงด้วย vega-embed
"""
import altair as alt
import numpy as np
import pandas as pd


'''


def main():
    src = APP.read_text(encoding="utf-8")
    nodes = top_level(src)
    targets = {
        REPO / "backend" / "app" / "__init__.py": '"""TFP backend (FastAPI + worker)"""\n',
        REPO / "backend" / "app" / "modeling" / "__init__.py": '"""การคำนวณที่ย้ายจากระบบเดิม"""\n',
        REPO / "backend" / "app" / "modeling" / "core.py": CORE_HEAD + build(CORE, src, nodes, core_transform) + "\n",
        REPO / "backend" / "app" / "charts.py": CHARTS_HEAD + build(CHARTS, src, nodes, chart_transform) + "\n",
    }
    tfp_dest = REPO / "backend" / "app" / "modeling" / "tfp.py"
    safe_io.ensure_absent([*targets, tfp_dest])
    for path, text in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_io.write_new(path, text)
    shutil.copyfile(REPO / "TFP.py", tfp_dest)
    for p in [*targets, tfp_dest]:
        print("เขียนแล้ว", p.relative_to(REPO))


if __name__ == "__main__":
    main()
