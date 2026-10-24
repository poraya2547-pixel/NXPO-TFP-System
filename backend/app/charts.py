"""ตัวสร้างกราฟ Altair ที่ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit 4c8aa71)

คัดลอกทั้งก้อนด้วย tools/refactor/extract_core.py ต่างจากต้นฉบับเพียงไม่วางกราฟลงหน้า Streamlit:
_nice_line_chart คืน chart และ _nice_line_chart_with_forecast คืน (chart, HTML คำอธิบายกราฟเดิม)
หน้าเว็บใหม่นำ chart.to_dict() (Vega-Lite) ไปแสดงด้วย vega-embed
"""
import altair as alt
import numpy as np
import pandas as pd


# ย้ายจาก TFP_App1.3.0.py:124-124 (4c8aa71)
FONT_FAMILY = "Prompt"  # <-- เปลี่ยนชื่อฟอนต์ตรงนี้ที่เดียวถ้าอยากเปลี่ยนฟอนต์ทั้งเว็บ


# ย้ายจาก TFP_App1.3.0.py:3536-3594 (4c8aa71)
def _nice_line_chart(series: pd.Series, color: str = "#F97316", height: int = 340):
    """สร้างกราฟเส้นด้วย Altair แทน st.line_chart เดิม เพื่อให้ดูสวยและอ่านง่าย
    ขึ้นกว่าเดิม: เส้นโค้งมน มีพื้นที่ใต้เส้นแบบไล่สีจาง ๆ, เส้น grid บางๆ,
    และ label บนแกนปีที่สุ่มแสดงเป็นช่วง ๆ (ไม่ยัดทุกปีจนอ่านไม่ออก) พร้อม
    tooltip บอกปีและค่าที่ชี้เมื่อเอาเมาส์ไปวาง — และปีบนแกน x เป็น string
    (ordinal) เสมอ กัน Vega-Lite ตีความเป็นตัวเลขแล้วใส่ , คั่นหลักพัน"""
    s = series.copy()
    s.index = s.index.map(str)
    df = s.reset_index()
    df.columns = ["ปี", "ค่า"]

    n = len(df)
    step = max(1, round(n / 12))
    tick_vals = df["ปี"].iloc[::step].tolist()
    if df["ปี"].iloc[-1] not in tick_vals:
        tick_vals.append(df["ปี"].iloc[-1])

    base = alt.Chart(df).encode(
        x=alt.X(
            "ปี:O", sort=None, title=None,
            axis=alt.Axis(values=tick_vals, labelAngle=0, grid=False,
                           domain=False, tickColor="#E9ECF1",
                           labelColor="#5B6B7C", labelFontSize=11, labelPadding=6),
        ),
        y=alt.Y(
            "ค่า:Q", title=None,
            axis=alt.Axis(grid=True, gridColor="#EEF1F5", gridDash=[3, 3],
                           domain=False, tickColor="#E9ECF1",
                           labelColor="#5B6B7C", labelFontSize=11),
        ),
        tooltip=[
            alt.Tooltip("ปี:O", title="ปี"),
            alt.Tooltip("ค่า:Q", title="ค่า", format=".4f"),
        ],
    )
    area = base.mark_area(
        interpolate="monotone",
        line=False,
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color=color, offset=0),
                alt.GradientStop(color="#FFFFFF", offset=1),
            ],
            x1=1, x2=1, y1=1, y2=0,
        ),
        opacity=0.35,
    )
    line = base.mark_line(
        interpolate="monotone", color=color, strokeWidth=2.6,
        point=alt.OverlayMarkDef(filled=True, size=32, color=color, stroke="#FFFFFF", strokeWidth=1.6),
    )
    chart = (
        (area + line)
        .properties(width="container", height=height, padding={"left": 4, "right": 10, "top": 8, "bottom": 4})
        .configure_view(strokeWidth=0)
        .configure_axis(labelFont=FONT_FAMILY, titleFont=FONT_FAMILY)
    )
    return chart


# ย้ายจาก TFP_App1.3.0.py:4026-4082 (4c8aa71)
def _mape_threshold_chart(roll_df: pd.DataFrame, height: int = 300):
    """สร้างกราฟเส้นเทียบ MAPE ของ ARIMA vs Naive ที่เปลี่ยนไปตามเกณฑ์ตัดจุดทดสอบ
    (จำนวนปีฝึกขั้นต่ำ) ทุกค่าพร้อมกันในกราฟเดียว แทนที่จะต้องเลื่อนสไลเดอร์ดูทีละจุด
    ช่วยให้เห็นว่า ARIMA แม่นขึ้นแบบมีแนวโน้มต่อเนื่องเมื่อข้อมูลฝึกมากขึ้นจริง หรือ
    เป็นแค่ความบังเอิญของตัวอย่างเล็กช่วงปลายอนุกรม (จุดที่มีจำนวนตัวอย่างเหลือน้อย
    จะมีเส้นแกว่งแรงกว่า ให้สังเกตช่วงที่จำนวนจุดยังพอสมควร (ดูจาก tooltip) เป็นหลัก)
    คำนวณจาก roll_df ที่ _run_rolling_backtest คืนมาแล้ว ไม่ต้องรัน ARIMA ซ้ำ
    คืนค่า Altair chart object หรือ None ถ้าไม่มีจุดที่คำนวณได้เลย"""
    train_sizes = sorted(roll_df["จำนวนปีที่ฝึก"].unique())

    def _mape(actual, pred):
        return float(np.mean(np.abs((actual - pred) / actual)) * 100)

    rows = []
    for t in train_sizes:
        sub = roll_df[roll_df["จำนวนปีที่ฝึก"] >= t]
        if len(sub) < 3:
            continue
        rows.append({"เกณฑ์": int(t), "โมเดล": "ARIMA", "MAPE": _mape(sub["ค่าจริง"], sub["ARIMA"]),
                     "จำนวนจุด": int(len(sub))})
        rows.append({"เกณฑ์": int(t), "โมเดล": "Naive", "MAPE": _mape(sub["ค่าจริง"], sub["Naive"]),
                     "จำนวนจุด": int(len(sub))})
        if "Drift" in sub.columns:
            rows.append({"เกณฑ์": int(t), "โมเดล": "Drift", "MAPE": _mape(sub["ค่าจริง"], sub["Drift"]),
                         "จำนวนจุด": int(len(sub))})
    if not rows:
        return None
    chart_df = pd.DataFrame(rows)

    color_scale = alt.Scale(domain=["ARIMA", "Naive", "Drift"], range=["#16324A", "#F97316", "#16A34A"])
    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "เกณฑ์:Q", title="จำนวนปีขั้นต่ำของข้อมูลฝึก",
            axis=alt.Axis(grid=False, domain=False, tickColor="#E9ECF1",
                           labelColor="#5B6B7C", labelFontSize=11, titlePadding=14),
        ),
        y=alt.Y(
            "MAPE:Q", title="MAPE เฉลี่ย (%)",
            axis=alt.Axis(grid=True, gridColor="#EEF1F5", gridDash=[3, 3],
                           domain=False, tickColor="#E9ECF1", labelColor="#5B6B7C", labelFontSize=11,
                           titlePadding=14),
        ),
        color=alt.Color("โมเดล:N", scale=color_scale, legend=alt.Legend(title=None, orient="top")),
        tooltip=[
            alt.Tooltip("เกณฑ์:Q", title="จำนวนปีขั้นต่ำของข้อมูลฝึก"),
            alt.Tooltip("โมเดล:N", title="โมเดล"),
            alt.Tooltip("MAPE:Q", title="MAPE", format=".2f"),
            alt.Tooltip("จำนวนจุด:Q", title="จำนวนจุดทดสอบที่เหลือ"),
        ],
    )
    line = base.mark_line(interpolate="monotone", strokeWidth=2.4)
    points = base.mark_point(size=45, filled=True)
    return (
        (line + points)
        .properties(height=height, padding={"left": 10, "right": 14, "top": 10, "bottom": 6})
        .configure_view(strokeWidth=0)
    )


# ย้ายจาก TFP_App1.3.0.py:4085-4187 (4c8aa71)
def _nice_line_chart_with_forecast(hist_series: pd.Series, forecast_df: pd.DataFrame,
                                    color: str = "#F97316", forecast_color: str = "#2F6FED",
                                    height: int = 340, display_from_year: int = None):
    """เหมือน _nice_line_chart แต่ต่อเส้นพยากรณ์ (เส้นประสีน้ำเงิน) และแถบ
    ช่วงพยากรณ์ 95% (พื้นที่สีน้ำเงินจาง ๆ) ต่อจากข้อมูลจริงให้ในกราฟเดียวกัน

    display_from_year (ใหม่): ถ้าระบุ จะตัดข้อมูลจริงก่อนปีนี้ออกจาก "การแสดงผล
    กราฟ" เท่านั้น (ไม่กระทบข้อมูลที่ใช้ฟิตโมเดล/คำนวณ ARIMA ซึ่งยังใช้ข้อมูลเต็ม
    ทุกปีตามเดิม) ใช้ตอนช่วงข้อมูลยาวมาก (เช่น 68 ปี) จนแกน x แน่น/กราฟรกเกินไป"""
    hist = hist_series.copy()
    hist.index = hist.index.map(int)
    if display_from_year is not None:
        hist = hist[hist.index >= display_from_year]
    years_hist = list(hist.index)
    years_fc = list(forecast_df.index)
    all_years = years_hist + years_fc
    year_order = [str(y) for y in all_years]

    df = pd.DataFrame({"ปี": year_order, "ปี_num": all_years})
    df["ข้อมูลจริง"] = df["ปี_num"].map(hist.to_dict())

    # เชื่อมจุดสุดท้ายของข้อมูลจริงเข้ากับเส้นพยากรณ์ ไม่ให้เส้นขาดตอน
    last_year, last_val = years_hist[-1], float(hist.iloc[-1])
    fc_mean = {last_year: last_val, **forecast_df["mean"].to_dict()}
    fc_lower = {last_year: last_val, **forecast_df["lower"].to_dict()}
    fc_upper = {last_year: last_val, **forecast_df["upper"].to_dict()}
    df["พยากรณ์"] = df["ปี_num"].map(fc_mean)
    df["ขอบล่าง"] = df["ปี_num"].map(fc_lower)
    df["ขอบบน"] = df["ปี_num"].map(fc_upper)

    n = len(df)
    step = max(1, round(n / 12))
    tick_vals = df["ปี"].iloc[::step].tolist()
    if df["ปี"].iloc[-1] not in tick_vals:
        tick_vals.append(df["ปี"].iloc[-1])

    x_enc = alt.X(
        "ปี:O", sort=year_order, title=None,
        axis=alt.Axis(values=tick_vals, labelAngle=0, grid=False,
                       domain=False, tickColor="#E9ECF1",
                       labelColor="#5B6B7C", labelFontSize=11, labelPadding=6),
    )
    y_axis = alt.Axis(grid=True, gridColor="#EEF1F5", gridDash=[3, 3],
                       domain=False, tickColor="#E9ECF1",
                       labelColor="#5B6B7C", labelFontSize=11)

    base = alt.Chart(df)

    ci_band = base.mark_area(opacity=0.15, color=forecast_color).encode(
        x=x_enc, y=alt.Y("ขอบล่าง:Q", title=None, axis=y_axis), y2="ขอบบน:Q",
    )
    hist_area = base.mark_area(
        interpolate="monotone", line=False,
        color=alt.Gradient(
            gradient="linear",
            stops=[alt.GradientStop(color=color, offset=0),
                   alt.GradientStop(color="#FFFFFF", offset=1)],
            x1=1, x2=1, y1=1, y2=0,
        ),
        opacity=0.35,
    ).encode(x=x_enc, y=alt.Y("ข้อมูลจริง:Q", title=None, axis=y_axis))
    hist_line = base.mark_line(
        interpolate="monotone", color=color, strokeWidth=2.6,
        point=alt.OverlayMarkDef(filled=True, size=30, color=color, stroke="#FFFFFF", strokeWidth=1.6),
    ).encode(
        x=x_enc, y=alt.Y("ข้อมูลจริง:Q"),
        tooltip=[alt.Tooltip("ปี:O", title="ปี"),
                 alt.Tooltip("ข้อมูลจริง:Q", title="ค่าจริง", format=".4f")],
    )
    fc_line = base.mark_line(
        interpolate="monotone", color=forecast_color, strokeWidth=2.6, strokeDash=[6, 4],
        point=alt.OverlayMarkDef(filled=True, size=30, color=forecast_color, stroke="#FFFFFF", strokeWidth=1.6),
    ).encode(
        x=x_enc, y=alt.Y("พยากรณ์:Q"),
        tooltip=[alt.Tooltip("ปี:O", title="ปี"),
                 alt.Tooltip("พยากรณ์:Q", title="ค่าพยากรณ์", format=".4f")],
    )
    fc_points = base.mark_point(color=forecast_color, filled=True, size=45).transform_filter(
        alt.datum["ปี_num"] > last_year
    ).encode(x=x_enc, y=alt.Y("พยากรณ์:Q"))

    chart = (
        (ci_band + hist_area + hist_line + fc_line + fc_points)
        .properties(width="container", height=height, padding={"left": 4, "right": 10, "top": 8, "bottom": 4})
        .configure_view(strokeWidth=0)
        .configure_axis(labelFont=FONT_FAMILY, titleFont=FONT_FAMILY)
    )
    # flex-wrap:wrap กัน legend ตกขอบขวาเวลาหน้าจอแคบ (แทนที่จะโดนตัดหาย
    # ก็ให้มันขึ้นบรรทัดใหม่แทน), row-gap เผื่อกรณีตัดบรรทัด
    legend_html = (
        f'<div class="chart-legend-row" style="display:flex;flex-wrap:wrap;justify-content:flex-end;column-gap:18px;row-gap:6px;'
        f'font-size:0.82rem;color:var(--brand-navy-soft);margin-top:-6px;">'
        f'<span style="white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:50%;background:{color};margin-right:5px;"></span>ข้อมูลจริง</span>'
        f'<span style="white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:50%;background:{forecast_color};margin-right:5px;"></span>พยากรณ์ (Drift)</span>'
        f'<span style="white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:2px;background:{forecast_color};opacity:0.3;margin-right:5px;"></span>'
        f'ช่วงพยากรณ์ 95%</span>'
        f'</div>'
    )
    return chart, legend_html

