"""ตัวสร้างกราฟที่ย้าย (backend/app/charts.py) ต้องให้ Vega-Lite spec และ HTML คำอธิบายกราฟตรงกับที่หน้าเดิมส่งให้ Streamlit ทุกค่า

ตัวสร้างเดิมดึงจาก TFP_App1.3.0.py ด้วย AST แล้วรันกับ st ปลอมที่จดสิ่งที่ถูกวางลงหน้า (altair_chart / markdown)
อินพุตเป็นผลจริงจาก snapshot ตามจุดเรียกในหน้าเดิม: 4615 (พยากรณ์ สูง 340 แสดงตั้งแต่ปี 2000), 4772 (MAPE ตามเกณฑ์),
4961 (TFP สูง 340), 5061 (ตัวแปรอิสระ สูง 280 — ทดสอบทุกคอลัมน์ของ model_df), 5903 / 5918 (แดชบอร์ดนำเสนอ สูง 230)
"""
import ast

import altair as alt
import numpy as np
import pandas as pd

import parity
from app import charts

NAMES = ["FONT_FAMILY", "_nice_line_chart", "_mape_threshold_chart", "_nice_line_chart_with_forecast"]


class FakeSt:
    def __init__(self):
        self.calls = []

    def altair_chart(self, chart, **kwargs):
        self.calls.append(("altair_chart", chart, kwargs))

    def markdown(self, body, **kwargs):
        self.calls.append(("markdown", body, kwargs))


def original_builders():
    src = (parity.REPO / "TFP_App1.3.0.py").read_text(encoding="utf-8")
    nodes = [n for n in ast.parse(src).body
             if (isinstance(n, ast.FunctionDef) and n.name in NAMES)
             or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) in NAMES)]
    assert len(nodes) == len(NAMES)
    st = FakeSt()
    ns = {"alt": alt, "np": np, "pd": pd, "st": st}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "TFP_App1.3.0.py", "exec"), ns)
    return ns, st


def test_line_charts_match_original(computed):
    ns, st = original_builders()
    out = computed["outputs"]
    cases = [(out["tfp_series"], "#F97316", 340), (out["tfp_series"], "#F97316", 230)]
    cases += [(out["model_df"][c].dropna().sort_index(), "#2F6FED", 280) for c in out["model_df"].columns]
    for series, color, height in cases:
        st.calls.clear()
        assert ns["_nice_line_chart"](series, color=color, height=height) is None
        assert [(c[0], c[2]) for c in st.calls] == [("altair_chart", {"use_container_width": True})]
        new = charts._nice_line_chart(series, color=color, height=height)
        assert new.to_dict() == st.calls[0][1].to_dict(), (series.name, height)


def test_forecast_charts_match_original(computed):
    ns, st = original_builders()
    out = computed["outputs"]
    for h in parity.oracle.HORIZONS:
        for kwargs in ({"height": 340, "display_from_year": 2000}, {"height": 230}):
            kwargs = dict(color="#F97316", forecast_color="#2F6FED", **kwargs)
            st.calls.clear()
            assert ns["_nice_line_chart_with_forecast"](out["tfp_series"], out[f"forecast.h{h}"], **kwargs) is None
            assert [(c[0], c[2]) for c in st.calls] == [("altair_chart", {"use_container_width": True}),
                                                        ("markdown", {"unsafe_allow_html": True})]
            chart, legend_html = charts._nice_line_chart_with_forecast(out["tfp_series"], out[f"forecast.h{h}"],
                                                                       **kwargs)
            assert chart.to_dict() == st.calls[0][1].to_dict(), (h, kwargs)
            assert isinstance(legend_html, str) and legend_html == st.calls[1][1], (h, kwargs)


def test_mape_threshold_chart_matches_original(computed):
    ns, st = original_builders()
    roll_df = computed["outputs"]["rolling"][0]
    old = ns["_mape_threshold_chart"](roll_df)
    new = charts._mape_threshold_chart(roll_df)
    assert old is not None and not st.calls
    assert new.to_dict() == old.to_dict()
