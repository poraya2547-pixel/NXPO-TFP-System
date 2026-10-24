"""ฟังก์ชันคำนวณที่ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit 4c8aa71)

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


# ย้ายจาก TFP_App1.3.0.py:1943-1947 (4c8aa71)
VARIABLE_ORDER = [
    "const", "FDI_GDP", "FEE_GDP", "ln_HDI", "ln_RDH_GDP", "RDG_GDP", "RDP_GDP",
    "ln_JOUR_GDP", "ln_PCT_GDP", "ln_PATENT_GDP", "ln_TUM_GDP", "INDUS_GDP",
    "TRADE_GDP", "MKTCOM", "ECM",
]


# ย้ายจาก TFP_App1.3.0.py:1949-1966 (4c8aa71)
VARIABLE_LABELS = {
    "const": "ค่าคงที่ : c",
    "ln_TFPI": "ดัชนีผลิตภาพปัจจัยการผลิตรวม (ตัวแปรตาม) : ln(TFPI)",
    "FDI_GDP": "สัดส่วนการลงทุนโดยตรงจากต่างประเทศต่อ GDP : FDI/GDP",
    "FEE_GDP": "ค่าธรรมเนียมในการใช้ทรัพย์สินทางปัญญาต่อ GDP : FEE/GDP",
    "ln_HDI": "ดัชนีการพัฒนามนุษย์ : ln(HDI)",
    "ln_RDH_GDP": "จำนวนนักวิจัยต่อประชากรล้านคน : ln(RDH)",
    "RDG_GDP": "สัดส่วนการลงทุนด้านวิจัยและพัฒนาของภาครัฐต่อ GDP : RDG/GDP",
    "RDP_GDP": "สัดส่วนการลงทุนด้านวิจัยและพัฒนาของภาคเอกชนต่อ GDP : RDP/GDP",
    "ln_JOUR_GDP": "สัดส่วนจำนวนสิ่งพิมพ์ทางวิทยาศาสตร์และเทคนิคต่อ GDP : ln(JOUR/GDP)",
    "ln_PCT_GDP": "จำนวนสนธิสัญญาความร่วมมือด้านสิทธิบัตรต่อ GDP : ln(PCT/GDP)",
    "ln_PATENT_GDP": "สัดส่วนจำนวนสิทธิบัตรต่อ GDP : ln(PATENT/GDP)",
    "ln_TUM_GDP": "สัดส่วนจำนวนอนุสิทธิบัตรต่อ GDP : ln(TUM/GDP)",
    "INDUS_GDP": "สัดส่วนมูลค่าเพิ่มภาคอุตสาหกรรมต่อ GDP : INDUS/GDP",
    "TRADE_GDP": "อัตราการเปิดกว้างทางการค้า : TRADE/GDP",
    "MKTCOM": "ดัชนีความซับซ้อนทางเศรษฐกิจด้านการค้า : MKTCOM",
    "ECM": "ECM",
}


# ย้ายจาก TFP_App1.3.0.py:2078-2106 (4c8aa71)
def var_label_with_abbr(code: str) -> str:
    """แสดงชื่อเต็มของตัวแปร แล้ววงเล็บรหัสย่อไว้ข้างหลัง
    เช่น "FDI_GDP" -> "การลงทุนโดยตรงจากต่างประเทศ (FDI/GDP)"
    ถ้าไม่มีในพจนานุกรม VARIABLE_LABELS จะคืนรหัสเดิม

    รองรับป้ายจากตาราง Stationarity (Short-run) ที่มีสัญลักษณ์ transform นำหน้า
    และ/หรือ lag ต่อท้าย เช่น "ΔFDI_GDP" หรือ "Δ²RDG_GDP (t-2)" — แกะสัญลักษณ์/lag
    ออกก่อน หาโค้ดตัวแปรฐานใน VARIABLE_LABELS แล้วประกอบกลับเป็น "Δ ชื่อเต็ม (ย่อ) (t-n)"
    ถ้าหาโค้ดฐานไม่เจอในพจนานุกรม จะคืนป้ายเดิมแบบไม่แปลง (เหมือนพฤติกรรมเดิม)"""
    m = re.match(r"^(Δ²?)([A-Za-z][A-Za-z0-9_]*)(\s*\(t-\d+\))?$", code)
    if m:
        diff_symbol, base_code, lag_part = m.groups()
        base_label = VARIABLE_LABELS.get(base_code)
        if base_label:
            if " : " in base_label:
                full_name, abbr = base_label.split(" : ", 1)
                base_display = f"{full_name} ({abbr})"
            else:
                base_display = base_label
            return f"{diff_symbol} {base_display}{lag_part or ''}"
        return str(code)

    label = VARIABLE_LABELS.get(code)
    if not label:
        return str(code)
    if " : " in label:
        full_name, abbr = label.split(" : ", 1)
        return f"{full_name} ({abbr})"
    return label


# ย้ายจาก TFP_App1.3.0.py:2109-2117 (4c8aa71)
def _var_full_name(code: str) -> str:
    """คืนเฉพาะชื่อเต็มภาษาไทยของตัวแปร (ไม่มีรหัสย่อต่อท้าย) ใช้ในข้อความอธิบาย
    เช่น การ์ดผลกระทบที่อยากพูดถึงตัวแปรด้วยชื่อเต็มล้วน ๆ อ่านลื่นกว่า"""
    label = VARIABLE_LABELS.get(code)
    if not label:
        return str(code)
    if " : " in label:
        return label.split(" : ", 1)[0]
    return label


# ย้ายจาก TFP_App1.3.0.py:2213-2213 (4c8aa71)
_VAR_CODE_RE = re.compile(r"^(?:d(?P<diff>[12])_)?(?P<base>.+?)(?:_lag(?P<lag>\d+))?$")


# ย้ายจาก TFP_App1.3.0.py:2216-2223 (4c8aa71)
def _parse_variable_code(code: str):
    m = _VAR_CODE_RE.match(str(code).strip())
    if not m:
        return str(code).strip(), 0, 0
    base = m.group("base")
    diff = int(m.group("diff")) if m.group("diff") else 0
    lag = int(m.group("lag")) if m.group("lag") else 0
    return base, diff, lag


# ย้ายจาก TFP_App1.3.0.py:2226-2237 (4c8aa71)
def _significance_stars(p_value) -> str:
    try:
        p = float(p_value)
    except (TypeError, ValueError):
        return ""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


# ย้ายจาก TFP_App1.3.0.py:2240-2257 (4c8aa71)
def _format_coefficient_cell(coef_value, p_value, diff: int, lag: int, show_significance: bool) -> str:
    try:
        coef_text = f"{float(coef_value):.4f}"
    except (TypeError, ValueError):
        return "-"
    parts = []
    if lag > 0:
        parts.append(f"(t-{lag})")
    parts.append(coef_text)
    if show_significance:
        star = _significance_stars(p_value)
        if star:
            parts.append(star)
    if diff == 1:
        parts.append("Δ")
    elif diff == 2:
        parts.append("Δ²")
    return " ".join(parts)


# ย้ายจาก TFP_App1.3.0.py:2260-2269 (4c8aa71)
def _unrounded_coefficient_table(res) -> pd.DataFrame:
    """ตารางสัมประสิทธิ์แบบไม่ปัดเศษ (โครงคอลัมน์เดียวกับ build_coefficient_tables)
    ใช้ป้อน _extract_raw_coefficients() เพื่อกันการปัดเศษซ้อน: เดิมดึงจากตารางที่ปัด
    4 ตำแหน่งแล้วไปปัด 3 ตำแหน่งอีกรอบตอนแสดงผล ทำให้ 0.111498 -> 0.1115 -> 0.112
    (ที่ถูกคือ 0.111) และทำให้ค่าที่ใช้คำนวณต่อ (standardized beta, scenario) คลาดเล็กน้อย"""
    return pd.DataFrame({
        "ตัวแปร": res.params.index,
        "ค่าสัมประสิทธิ์": res.params.values,
        "p-value": res.pvalues.values,
    })


# ย้ายจาก TFP_App1.3.0.py:2272-2294 (4c8aa71)
def _extract_raw_coefficients(df: pd.DataFrame) -> dict:
    """ดึงค่าสัมประสิทธิ์ดิบ (ตัวเลขจริง ไม่ใช่สตริงจัดรูปแบบแบบใน _merge_coefficient_tables)
    จากตาราง lr_table/sr_table ที่ได้จาก build_coefficient_tables()
    คืนค่าเป็น dict: base_var -> {"coef", "p", "diff", "lag", "raw_code"}
    ถ้าตัวแปรฐานเดียวกันมีหลายแถว (เช่น มีหลาย lag) จะเก็บแถวสุดท้ายไว้ ให้ตรงกับ
    ตัวเลขที่แสดงในตารางสัมประสิทธิ์รวมที่ผู้ใช้เห็นอยู่แล้วในหน้าหลัก"""
    var_col, coef_col = df.columns[0], df.columns[1]
    p_col = df.columns[2] if len(df.columns) > 2 else None
    out = {}
    for _, row in df.iterrows():
        base, diff, lag = _parse_variable_code(row[var_col])
        try:
            coef = float(row[coef_col])
        except (TypeError, ValueError):
            continue
        p_val = None
        if p_col is not None:
            try:
                p_val = float(row[p_col])
            except (TypeError, ValueError):
                p_val = None
        out[base] = {"coef": coef, "p": p_val, "diff": diff, "lag": lag, "raw_code": row[var_col]}
    return out


# ย้ายจาก TFP_App1.3.0.py:2297-2335 (4c8aa71)
def _merge_coefficient_tables(lr_table: pd.DataFrame, sr_table: pd.DataFrame) -> pd.DataFrame:
    """แปลงตารางระยะยาว/ระยะสั้นจาก TFP.py (คอลัมน์: รหัสตัวแปรดิบ, สัมประสิทธิ์, p-value)
    เป็นตารางเดียวแบบฟอร์มรายงานทางการ — คอลัมน์ระยะยาวแสดงเฉพาะค่าสัมประสิทธิ์
    (ไม่มีดาว/Δ/lag) ส่วนคอลัมน์ระยะสั้นแสดง (t-N) + ค่า + ดาวนัยสำคัญ + Δ/Δ²

    หมายเหตุ: รูปแบบรหัสตัวแปร (d1_/d2_ prefix, _lagN suffix) และรายชื่อตัวแปรเต็ม
    อิงจากตัวอย่างข้อมูลจริงที่ได้รับมา — ถ้า TFP.py มีตัวแปรอื่นเพิ่มเติมนอกเหนือจาก
    VARIABLE_LABELS ด้านบน ให้เพิ่มรายการในดิกชันนารีนั้น"""

    def build_map(df: pd.DataFrame, show_significance: bool) -> dict:
        var_col, coef_col = df.columns[0], df.columns[1]
        p_col = df.columns[2] if len(df.columns) > 2 else None
        out = {}
        for _, row in df.iterrows():
            base, diff, lag = _parse_variable_code(row[var_col])
            p_val = row[p_col] if p_col is not None else None
            out[base] = _format_coefficient_cell(row[coef_col], p_val, diff, lag, show_significance)
        return out

    lr_map = build_map(lr_table, show_significance=False)
    sr_map = build_map(sr_table, show_significance=True)

    rows = []
    for base in VARIABLE_ORDER:
        label = VARIABLE_LABELS.get(base, base)
        lr_val = lr_map.get(base, "n.a." if base == "ECM" else "-")
        sr_val = sr_map.get(base, "-")
        rows.append([label, lr_val, sr_val])

    # กันตกหล่น: ตัวแปรที่มีในข้อมูลจริงแต่ไม่อยู่ใน VARIABLE_ORDER ด้านบน
    known = set(VARIABLE_ORDER)
    extra_bases = [b for b in list(lr_map) + list(sr_map) if b not in known]
    for base in dict.fromkeys(extra_bases):
        rows.append([VARIABLE_LABELS.get(base, base), lr_map.get(base, "-"), sr_map.get(base, "-")])

    return pd.DataFrame(
        rows,
        columns=["ตัวแปร", "ค่าสัมประสิทธิ์\nสมการระยะยาว", "ค่าสัมประสิทธิ์\nสมการระยะสั้น"],
    )


# ย้ายจาก TFP_App1.3.0.py:3373-3373 (4c8aa71)
_TREND_LABEL = {"c": "ค่าคงที่", "ct": "ค่าคงที่ + แนวโน้ม", "n": "ไม่มีค่าคงที่"}


# ย้ายจาก TFP_App1.3.0.py:3376-3416 (4c8aa71)
def _build_adf_detail_table(model_df: pd.DataFrame, dep_ln: str,
                            lr_vars: list, sr_spec: list) -> pd.DataFrame:
    """ตารางผล ADF รายตัวแปร — แสดงครบทุกตัวแปร (ตัวแปรตาม + CANDIDATE_VARS ทั้งหมด)
    เรียงตามตารางค่าสัมประสิทธิ์ ตัวที่ไม่ได้อยู่ในสมการ (หรือไม่มีข้อมูล) แสดง "–"
    เหมือนตารางค่าสัมประสิทธิ์ ถ้าคณะวิจัยเพิ่มตัวแปรเข้าสมการ แถวนั้นจะคำนวณให้อัตโนมัติ
    เรียก adf_report() จาก TFP.py ตัวเดียวกับตาราง Diagnostics — ไม่ได้คำนวณใหม่ด้วยวิธีอื่น"""
    sr_bases = [c for c, _, _ in sr_spec]
    variables = list(dict.fromkeys([dep_ln] + list(CANDIDATE_VARS) + list(lr_vars) + sr_bases))
    value_cols = ["Level: t*", "Level: ค่าวิกฤต 5%", "ΔY: รูปแบบ", "ΔY: t*", "ΔY: ค่าวิกฤต 5%",
                  "ΔY: lag", "ΔY: n", "Δ²Y: t*", "Δ²Y: ค่าวิกฤต 5%", "ผลสรุป"]
    rows = []
    codes = []
    for v in variables:
        codes.append(v)
        used = v == dep_ln or v in lr_vars or v in sr_bases
        used_in = ("ตัวแปรตาม" if v == dep_ln else
                   " / ".join(s for s, ok in (("ระยะยาว", v in lr_vars), ("ระยะสั้น", v in sr_bases)) if ok)
                   or "ไม่ได้ใช้")
        if not used or v not in model_df.columns:
            rows.append({"ตัวแปร": var_label_with_abbr(v),
                         "ใช้ในสมการ": used_in if v in model_df.columns else "ไม่มีข้อมูล",
                         **{c: "–" for c in value_cols}})
            continue
        r = adf_report(model_df[v], v)
        rows.append({
            "ตัวแปร": var_label_with_abbr(v),
            "ใช้ในสมการ": used_in,
            "Level: t*": f"{r['adf_level_t']:.3f}",
            "Level: ค่าวิกฤต 5%": f"{r['adf_level_crit5']:.3f}",
            "ΔY: รูปแบบ": _TREND_LABEL.get(ADF_DIFF_TREND.get(v, "c"), ADF_DIFF_TREND.get(v, "c")),
            "ΔY: t*": f"{r['adf_diff_t']:.3f}",
            "ΔY: ค่าวิกฤต 5%": f"{r['adf_diff_crit5']:.3f}",
            "ΔY: lag": int(r["diff_lag"]),
            "ΔY: n": int(r["diff_nobs"]),
            "Δ²Y: t*": _fmt3(r.get("adf_diff2_t")),
            "Δ²Y: ค่าวิกฤต 5%": _fmt3(r.get("adf_diff2_crit5")),
            "ผลสรุป": r["order_of_integration"],
        })
    out = pd.DataFrame(rows)
    out.attrs["codes"] = codes  # รหัสดิบ ใช้แสดงช่องตัวแปรแบบสองบรรทัดบนเว็บ
    return out


# ย้ายจาก TFP_App1.3.0.py:3425-3430 (4c8aa71)
def _fmt3(x) -> str:
    """แสดงทศนิยม 3 ตำแหน่ง หรือ '–' ถ้าไม่มีค่า (เช่น ข้อมูลไม่พอทดสอบ Δ²)"""
    try:
        return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{float(x):.3f}"
    except (TypeError, ValueError):
        return "–"


# ย้ายจาก TFP_App1.3.0.py:3597-3697 (4c8aa71)
def _auto_arima_forecast(series: pd.Series, periods: int,
                          max_p: int = 4, max_d: int = 2, max_q: int = 4):
    """หาโมเดล ARIMA(p,d,q) ที่เหมาะกับข้อมูลที่สุด ตามขั้นตอนในหัวข้อ 2.4.1–2.4.3 ของเล่ม
    1) หาอันดับผลต่าง d ด้วย ADF (เลือก lag ด้วย SBC และ maxlag ตามสูตร EViews เหมือนหัวข้อ 2.5)
    2) ประมาณค่าแบบจำลองทุกชุด p, q ในช่วงที่กำหนด โดยมีค่าคงที่ θ0 ในสมการของ Δ^d Y
       ตามสมการในหัวข้อ 2.4.1 (statsmodels ไม่ใส่ค่าคงที่ให้เองเมื่อ d ≥ 1 จึงต้องระบุ trend)
    3) ตรวจความเหมาะสม: ค่าคลาดเคลื่อนเป็นตัวรบกวนขาว (Ljung–Box p ≥ 0.05) และ
       สัมประสิทธิ์ AR/MA ทุกตัวมีนัยสำคัญที่ระดับ 0.05
    4) เลือกแบบจำลองที่ AIC ต่ำที่สุดจากแบบจำลองที่ผ่านข้อ 3 (ถ้าไม่มีตัวใดผ่านเลย
       จะเลือกจาก AIC ต่ำที่สุดของทุกแบบจำลอง เพื่อให้ยังพยากรณ์ได้)
    จากนั้นพยากรณ์ล่วงหน้า `periods` ปี พร้อมช่วงพยากรณ์ 95%

    คืนค่า (forecast_df, order) โดย forecast_df มี index เป็นปีในอนาคต และ
    คอลัมน์ mean / lower / upper ส่วน order คือ (p, d, q) ที่เลือกใช้จริง
    ถ้าหาโมเดลที่ fit ได้ไม่สำเร็จเลย จะ fallback เป็น random walk with drift (0,1,0)"""
    from statsmodels.stats.diagnostic import acorr_ljungbox
    y = series.astype(float).values
    T = len(y)

    # หาลำดับ differencing (d) ที่เหมาะสมก่อนด้วย ADF test (Augmented Dickey-Fuller)
    # แทนที่จะปล่อยให้ AIC เป็นตัวเลือก d เอง เพราะ AIC เปรียบเทียบข้าม d ต่างกัน
    # ไม่ได้ตรงๆ — ใช้ SBC เลือก lag และ maxlag ตามสูตร EViews ให้ตรงกับหัวข้อ 2.4.3 และ 2.5
    _adf_maxlag = int(min(T / 3, 12) * (T / 100) ** 0.25)

    def _select_d(vals, max_diff):
        d = 0
        cur = vals.copy()
        while d < max_diff:
            try:
                pvalue = adfuller(cur, autolag="BIC", maxlag=_adf_maxlag)[1]
            except Exception:
                break
            if pvalue < 0.05:
                break
            cur = np.diff(cur)
            d += 1
        return d

    def _trend_for_d(d):
        # ค่าคงที่ θ0 ในสมการของ Δ^d Y เทียบเท่ากับพจน์แนวโน้มอันดับ d ในข้อมูลระดับ
        # d=0 → ค่าคงที่ ('c'), d=1 → แนวโน้มเชิงเส้น ('t' = drift), d=2 → แนวโน้มกำลังสอง
        return {0: "c", 1: "t"}.get(d, [0] * d + [1])

    def _passes_diagnostics(fit, p, q, d):
        try:
            resid = np.asarray(fit.resid)[d:]  # ตัดค่าคลาดเคลื่อนช่วงแรกที่เกิดจากการหาผลต่าง
            lb_lag = max(min(10, len(resid) // 5), p + q + 1)
            if lb_lag >= len(resid):
                return False
            lb_p = float(acorr_ljungbox(resid, lags=[lb_lag], model_df=p + q)["lb_pvalue"].iloc[0])
            if not np.isfinite(lb_p) or lb_p < 0.05:
                return False
            names = list(fit.param_names)
            pvals = np.asarray(fit.pvalues)
            arma_p = [pv for nm, pv in zip(names, pvals) if nm.startswith(("ar.", "ma."))]
            return all(np.isfinite(pv) and pv < 0.05 for pv in arma_p)
        except Exception:
            return False

    fixed_d = _select_d(y, max_d)
    trend = _trend_for_d(fixed_d)

    candidates = []  # (aic, order, fit, ผ่านการตรวจสอบหรือไม่)
    for p in range(0, max_p + 1):
        for d in (fixed_d,):
            for q in range(0, max_q + 1):
                if p == 0 and q == 0:
                    continue
                try:
                    fit = ARIMA(y, order=(p, d, q), trend=trend).fit()
                    if np.isfinite(fit.aic):
                        candidates.append((fit.aic, (p, d, q), fit, _passes_diagnostics(fit, p, q, d)))
                except Exception:
                    continue

    best_fit = None
    best_order = None
    if candidates:
        passed = [c for c in candidates if c[3]]
        pool = passed if passed else candidates
        _, best_order, best_fit, _ = min(pool, key=lambda c: c[0])

    if best_fit is None:
        # กันเหนียว: ถ้าไม่มีชุด (p,d,q) ไหน fit ได้เลย ใช้ random walk with
        # drift แทน (โมเดลพื้นฐานที่สุด ยังพยากรณ์แนวโน้มต่อได้เสมอ)
        best_fit = ARIMA(y, order=(0, 1, 0), trend="t").fit()
        best_order = (0, 1, 0)

    fc = best_fit.get_forecast(steps=periods)
    summary = fc.summary_frame(alpha=0.05)
    last_year = int(series.index.max())
    future_years = [last_year + i for i in range(1, periods + 1)]
    forecast_df = pd.DataFrame(
        {
            "mean": summary["mean"].values,
            "lower": summary["mean_ci_lower"].values,
            "upper": summary["mean_ci_upper"].values,
        },
        index=future_years,
    )
    return forecast_df, best_order


# ย้ายจาก TFP_App1.3.0.py:3700-3707 (4c8aa71)
def _drift_forecast(train: pd.Series, h: int) -> float:
    """Random walk with drift: ค่าพยากรณ์ล่วงหน้า h ปี = ค่าปีล่าสุด + h × การเปลี่ยนแปลง
    เฉลี่ยต่อปีของข้อมูลฝึก (Hyndman & Athanasopoulos, 2021) — ง่ายพอ ๆ กับ Naive แต่
    มีแนวโน้ม ใช้เป็นเส้นฐานเทียบตัวที่ 2 สำหรับอนุกรมที่โตต่อเนื่องอย่างดัชนี TFP"""
    y = train.astype(float).values
    if len(y) < 2:
        return float(y[-1])
    return float(y[-1] + h * (y[-1] - y[0]) / (len(y) - 1))


# ย้ายจาก TFP_App1.3.0.py:3710-3737 (4c8aa71)
def _drift_forecast_interval(series: pd.Series, periods: int, level: float = 0.95):
    """พยากรณ์ด้วย Random walk with drift พร้อมช่วงพยากรณ์ (กราฟพยากรณ์หลัก)

    เป็นวิธีพยากรณ์หลักตามหัวข้อ 2.4.7.1 ของเล่ม เพราะข้อมูล TFP เป็นข้อมูลรายปีที่มีจำนวน
    ค่าสังเกตน้อยและมีแนวโน้มต่อเนื่อง และวิธีนี้ไม่ต้องประมาณค่าพารามิเตอร์หลายตัว
    ส่วน ARIMA และ Naive ใช้เป็นเกณฑ์เปรียบเทียบใน backtest และ Diebold–Mariano test

    ค่าพยากรณ์ล่วงหน้า h ปี : ŷ(T+h) = y(T) + h × c โดย c = (y(T) − y(1)) / (T − 1)
    ส่วนเบี่ยงเบนมาตรฐานของค่าพยากรณ์ : σ̂_h = σ̂ × √(h × (1 + h / (T − 1)))
    (σ̂ = ส่วนเบี่ยงเบนมาตรฐานของการเปลี่ยนแปลงรายปี; Hyndman & Athanasopoulos, 2021)

    คืนค่า DataFrame ที่มี index เป็นปีในอนาคต และคอลัมน์ mean / lower / upper
    (รูปแบบเดียวกับ _auto_arima_forecast เพื่อใช้กับกราฟและตารางเดิมได้ทันที)"""
    from scipy import stats as _sps
    y = series.astype(float).values
    T = len(y)
    diffs = np.diff(y)
    c = float(diffs.mean()) if T > 1 else 0.0
    sigma = float(np.std(diffs, ddof=1)) if T > 2 else 0.0
    z = float(_sps.norm.ppf(0.5 + level / 2))
    last_year = int(series.index.max())
    h = np.arange(1, periods + 1)
    mean = y[-1] + h * c
    se = sigma * np.sqrt(h * (1 + h / (T - 1))) if T > 1 else np.zeros(len(h))
    return pd.DataFrame(
        {"mean": mean, "lower": mean - z * se, "upper": mean + z * se},
        index=[last_year + int(i) for i in h],
    )


# ย้ายจาก TFP_App1.3.0.py:3740-3763 (4c8aa71)
def _diebold_mariano(actual, pred1, pred2, h: int = 1):
    """ทดสอบ Diebold–Mariano (1995) ว่าวิธีพยากรณ์ 1 กับ 2 แม่นต่างกันอย่างมีนัยสำคัญไหม
    ใช้ฟังก์ชันความสูญเสียแบบกำลังสอง d_t = e1_t^2 − e2_t^2 และปรับสำหรับตัวอย่างเล็ก
    ตาม Harvey, Leybourne & Newbold (1997) แล้วเทียบกับการแจกแจง t (m−1) แบบสองทาง
    H0: แม่นเท่ากัน · mean_d < 0 แปลว่าวิธีที่ 1 คลาดเคลื่อนน้อยกว่า
    คืนค่า dict(stat, pvalue, m, mean_d) หรือ None ถ้าจุดทดสอบน้อยเกินไป/ความแปรปรวนเป็นศูนย์"""
    from scipy import stats as _sps
    a = np.asarray(actual, dtype=float)
    d = (a - np.asarray(pred1, dtype=float)) ** 2 - (a - np.asarray(pred2, dtype=float)) ** 2
    d = d[np.isfinite(d)]
    m = len(d)
    if m < 3:
        return None
    dbar = float(d.mean())
    dc = d - dbar
    var = float(np.mean(dc * dc))
    for k in range(1, h):
        var += 2 * float(np.mean(dc[k:] * dc[:-k]))
    if not np.isfinite(var) or var <= 0:
        return None
    dm = dbar / math.sqrt(var / m)
    stat = dm * math.sqrt((m + 1 - 2 * h + h * (h - 1) / m) / m)
    pvalue = float(2 * (1 - _sps.t.cdf(abs(stat), df=m - 1)))
    return {"stat": float(stat), "pvalue": pvalue, "m": m, "mean_d": dbar}


# ย้ายจาก TFP_App1.3.0.py:3766-3773 (4c8aa71)
def _dm_verdict(dm: dict, name1: str, name2: str, alpha: float = 0.05) -> str:
    """แปลผล DM เป็นข้อความสั้น ๆ สำหรับแสดงบนหน้าเว็บ"""
    if not dm:
        return "จุดทดสอบไม่เพียงพอสำหรับการทดสอบ"
    if dm["pvalue"] >= alpha:
        return f"ความแม่นยำไม่แตกต่างกันอย่างมีนัยสำคัญที่ระดับ {alpha:g}"
    better = name1 if dm["mean_d"] < 0 else name2
    return f"{better} แม่นยำกว่าอย่างมีนัยสำคัญที่ระดับ {alpha:g}"


# ย้ายจาก TFP_App1.3.0.py:3776-3776 (4c8aa71)
_MODEL_COLORS = {"ARIMA": "#16324A", "Naive": "#F97316", "Drift": "#16A34A"}


# ย้ายจาก TFP_App1.3.0.py:3780-3780 (4c8aa71)
_PCT_SCALED_VARS = {"FDI_GDP", "FEE_GDP", "RDG_GDP", "RDP_GDP", "TRADE_GDP", "INDUS_GDP"}


# ย้ายจาก TFP_App1.3.0.py:3781-3781 (4c8aa71)
_MODEL_LABELS = {"ARIMA": "ARIMA", "Naive": "Naive", "Drift": "Random walk with drift"}


# ย้ายจาก TFP_App1.3.0.py:3785-3831 (4c8aa71)
def _run_backtest(tfp_series: pd.Series, min_train: int = 8, test_years: int = 5):
    """ทดสอบความแม่นยำของแบบจำลองย้อนหลัง (holdout backtest) — ไม่ใช้ทฤษฎีใหม่
    เพิ่มเติมจากที่มีอยู่แล้วเลย แค่เรียก _auto_arima_forecast ตัวเดิมซ้ำ โดย:
    1) ซ่อนข้อมูล `test_years` ปีสุดท้ายไว้ (แสร้งทำเป็นว่ายังไม่รู้อนาคต)
    2) ให้โมเดล ARIMA พยากรณ์ปีที่ซ่อนไว้จากข้อมูลที่เหลือ
    3) เทียบค่าพยากรณ์กับค่าจริงที่รู้อยู่แล้ว ว่าใกล้เคียงกันแค่ไหน
    พร้อมเทียบกับ "Naive forecast" (สมมติว่าปีต่อๆ ไปเท่ากับปีสุดท้ายก่อนซ่อนข้อมูล
    เฉยๆ ไม่ใช้แบบจำลองใดเลย) เป็นเส้นฐานว่า ARIMA พยากรณ์แม่นกว่าการเดาเปล่าๆ แค่ไหน
    คืนค่า (bt_df, metrics, None) หรือ (None, None, ข้อความเหตุผล) ถ้าทำไม่ได้"""
    n = len(tfp_series)
    max_test = n - min_train
    if max_test < 1:
        return None, None, f"ข้อมูลไม่พอสำหรับทดสอบย้อนหลัง (ต้องมีอย่างน้อย {min_train + 1} ปี)"
    test_years = min(test_years, max_test)
    train = tfp_series.iloc[:-test_years]
    test = tfp_series.iloc[-test_years:]
    try:
        bt_forecast_df, bt_order = _auto_arima_forecast(train, test_years)
    except Exception as e:
        return None, None, f"ทดสอบย้อนหลังไม่สำเร็จ: {e}"

    naive_val = float(train.iloc[-1])  # Naive forecast: คงค่าปีสุดท้ายก่อนซ่อนข้อมูลไว้ทุกปีถัดไป
    rows = []
    for h, (yr, actual) in enumerate(test.items(), start=1):
        arima_pred = float(bt_forecast_df.loc[int(yr), "mean"]) if int(yr) in bt_forecast_df.index else None
        rows.append({"ปี": int(yr), "ค่าจริง": float(actual), "ARIMA": arima_pred, "Naive": naive_val,
                     "Drift": _drift_forecast(train, h)})
    bt_df = pd.DataFrame(rows).set_index("ปี")

    def _mape(actual, pred):
        return float(np.mean(np.abs((actual - pred) / actual)) * 100)

    def _rmse(actual, pred):
        return float(np.sqrt(np.mean((actual - pred) ** 2)))

    metrics = {
        "arima_mape": _mape(bt_df["ค่าจริง"], bt_df["ARIMA"]),
        "arima_rmse": _rmse(bt_df["ค่าจริง"], bt_df["ARIMA"]),
        "naive_mape": _mape(bt_df["ค่าจริง"], bt_df["Naive"]),
        "naive_rmse": _rmse(bt_df["ค่าจริง"], bt_df["Naive"]),
        "drift_mape": _mape(bt_df["ค่าจริง"], bt_df["Drift"]),
        "drift_rmse": _rmse(bt_df["ค่าจริง"], bt_df["Drift"]),
        "order": bt_order,
        "test_years": test_years,
        "train_years": len(train),
    }
    return bt_df, metrics, None


# ย้ายจาก TFP_App1.3.0.py:3835-3945 (4c8aa71)
def _run_rolling_backtest(tfp_series: pd.Series, min_train: int = 8, step_ahead: int = 1,
                           max_windows: Optional[int] = None, crisis_years: tuple = None):
    """ทดสอบย้อนหลังแบบ rolling-origin (expanding window) — ต่อยอดจาก _run_backtest
    ด้านบนซึ่งซ่อนข้อมูลไว้แค่ช่วงเดียว (holdout ก้อนเดียวท้ายอนุกรม) จุดอ่อนของ
    วิธีนั้นคือถ้าช่วงที่ซ่อนไว้บังเอิญมีเหตุการณ์พิเศษปนอยู่ (เช่น โควิด-19 ที่ทำให้
    เกิด structural break) ผลเปรียบเทียบจะสะท้อนแค่ "ช่วงนั้น" ไม่ใช่ความสามารถ
    โดยรวมของโมเดล การเลือกโมเดลจากผลของช่วงทดสอบช่วงเดียวจึงเสี่ยงต่อการ overfit
    ต่อชุดทดสอบนั้นเอง

    วิธีนี้แก้ปัญหาโดยเลื่อนจุดเริ่มทดสอบ (origin) ไปทีละปีทั่วทั้งอนุกรมแทน:
    origin แรก = ฝึกด้วยข้อมูล min_train ปีแรก แล้วทาย step_ahead ปีถัดไป
    origin ถัดไป = เพิ่มข้อมูลฝึกอีก 1 ปี แล้วทายปีถัดไปอีก ไปเรื่อยๆ จนหมดข้อมูล
    จากนั้นรวมผลความคลาดเคลื่อนจากทุก origin เข้าด้วยกัน ทำให้เห็นภาพว่า ARIMA
    แม่นกว่า Naive โดยเฉลี่ยตลอดทั้งอนุกรมจริงหรือไม่ ไม่ใช่แค่ในช่วงทดสอบช่วงเดียว

    ถ้าระบุ crisis_years=(ปีเริ่ม, ปีสิ้นสุด) จะแยกสรุปผลเพิ่มเป็น 2 ช่วง คือ
    ช่วงปกติ (นอกช่วงวิกฤต) กับช่วงวิกฤต เพื่อดูว่าโมเดลไหนแม่นกว่าในแต่ละบริบท
    แยกกันชัดๆ แทนที่จะปนกันเป็นตัวเลขก้อนเดียว

    หมายเหตุ: เพื่อไม่ให้ต้องรัน ARIMA grid search ซ้ำมากเกินไปจนช้า (แต่ละ origin
    ต้องหา (p,d,q) ที่ดีที่สุดใหม่) จึงจำกัดกริดให้แคบกว่า _auto_arima_forecast
    เล็กน้อย (max_p=3, max_q=3) ค่าเริ่มต้นทดสอบครบทุกจุด ถ้าระบุ max_windows และจำนวน
    จุดทดสอบมากกว่านั้น จะเลือกจุดแบบเว้นระยะเท่า ๆ กันแทนการทดสอบทุกจุด

    คืนค่า (origins_df, metrics, None) หรือ (None, None, ข้อความเหตุผล) ถ้าทำไม่ได้"""
    n = len(tfp_series)
    last_train_size = n - step_ahead
    if last_train_size < min_train:
        return None, None, (
            f"ข้อมูลไม่พอสำหรับ rolling-origin backtest "
            f"(ต้องมีอย่างน้อย {min_train + step_ahead} ปี)"
        )

    train_sizes = list(range(min_train, last_train_size + 1))
    # ค่าเริ่มต้นทดสอบทุกจุดเริ่มพยากรณ์ (เลื่อนทีละ 1 ปี ตามหัวข้อ 2.4.6.2 ของเล่ม)
    # ถ้าระบุ max_windows จะเลือกจุดแบบเว้นระยะเท่า ๆ กันไม่เกินจำนวนนั้น เพื่อความเร็ว
    if max_windows and len(train_sizes) > max_windows:
        idx = np.linspace(0, len(train_sizes) - 1, max_windows).round().astype(int)
        train_sizes = sorted(set(train_sizes[i] for i in idx))

    rows = []
    for t in train_sizes:
        train = tfp_series.iloc[:t]
        target_pos = t + step_ahead - 1
        if target_pos >= n:
            continue
        target_year = int(tfp_series.index[target_pos])
        actual = float(tfp_series.iloc[target_pos])
        naive_val = float(train.iloc[-1])  # Naive: คงค่าปีฝึกล่าสุดไปเป็นค่าทาย
        try:
            fc_df, _ = _auto_arima_forecast(train, step_ahead, max_p=3, max_d=2, max_q=3)
            arima_pred = float(fc_df.loc[target_year, "mean"]) if target_year in fc_df.index else None
        except Exception:
            arima_pred = None
        if arima_pred is None:
            continue
        rows.append({
            "ปีที่ทาย": target_year,
            "จำนวนปีที่ฝึก": t,
            "ค่าจริง": actual,
            "ARIMA": arima_pred,
            "Naive": naive_val,
            "Drift": _drift_forecast(train, step_ahead),
        })

    if not rows:
        return None, None, "ทดสอบ rolling-origin ไม่สำเร็จ (ไม่มีจุดทดสอบที่คำนวณได้)"

    origins_df = pd.DataFrame(rows)

    def _mape(actual, pred):
        return float(np.mean(np.abs((actual - pred) / actual)) * 100)

    def _rmse(actual, pred):
        return float(np.sqrt(np.mean((actual - pred) ** 2)))

    metrics = {
        "arima_mape": _mape(origins_df["ค่าจริง"], origins_df["ARIMA"]),
        "naive_mape": _mape(origins_df["ค่าจริง"], origins_df["Naive"]),
        "arima_rmse": _rmse(origins_df["ค่าจริง"], origins_df["ARIMA"]),
        "naive_rmse": _rmse(origins_df["ค่าจริง"], origins_df["Naive"]),
        "drift_mape": _mape(origins_df["ค่าจริง"], origins_df["Drift"]),
        "drift_rmse": _rmse(origins_df["ค่าจริง"], origins_df["Drift"]),
        "n_windows": len(origins_df),
        # Diebold–Mariano: ทดสอบว่าความต่างของความแม่นยำมีนัยสำคัญทางสถิติจริงไหม
        "dm_arima_naive": _diebold_mariano(origins_df["ค่าจริง"], origins_df["ARIMA"], origins_df["Naive"], h=step_ahead),
        "dm_drift_naive": _diebold_mariano(origins_df["ค่าจริง"], origins_df["Drift"], origins_df["Naive"], h=step_ahead),
        "dm_drift_arima": _diebold_mariano(origins_df["ค่าจริง"], origins_df["Drift"], origins_df["ARIMA"], h=step_ahead),
    }
    # วิธีที่แม่นที่สุดจาก rolling backtest (MAPE ต่ำสุด) — ใช้แสดงเป็นป้ายแนะนำเท่านั้น
    # (กราฟพยากรณ์หลักใช้ Drift ผ่าน _drift_forecast_interval)
    metrics["best_model"] = min(("ARIMA", "Naive", "Drift"), key=lambda k: metrics[f"{k.lower()}_mape"])

    if crisis_years:
        y0, y1 = crisis_years
        _in_crisis = origins_df["ปีที่ทาย"].between(y0, y1)
        for label, mask in (("normal", ~_in_crisis), ("crisis", _in_crisis)):
            sub = origins_df[mask]
            if len(sub) > 0:
                metrics[f"arima_mape_{label}"] = _mape(sub["ค่าจริง"], sub["ARIMA"])
                metrics[f"naive_mape_{label}"] = _mape(sub["ค่าจริง"], sub["Naive"])
                metrics[f"drift_mape_{label}"] = _mape(sub["ค่าจริง"], sub["Drift"])
                metrics[f"drift_mape_{label}"] = _mape(sub["ค่าจริง"], sub["Drift"])
                metrics[f"n_{label}"] = len(sub)
            else:
                metrics[f"arima_mape_{label}"] = None
                metrics[f"naive_mape_{label}"] = None
                metrics[f"drift_mape_{label}"] = None
                metrics[f"n_{label}"] = 0

    return origins_df, metrics, None


# ย้ายจาก TFP_App1.3.0.py:4190-4222 (4c8aa71)
def _compute_influence_df(model_df: pd.DataFrame, dep_ln: str, active_lr_vars: list, lr_raw_map: dict):
    """คำนวณสัดส่วนอิทธิพล (standardized coefficient) ของตัวแปรอิสระแต่ละตัวในสมการ
    ระยะยาว เทียบกันเป็น % (รวมกันได้ 100%) — ดึงตรรกะเดิมออกมาจากหน้า "พยากรณ์ TFP"
    เป็นฟังก์ชันกลาง เพื่อให้หน้า "แดชบอร์ดสำหรับนำเสนอ (สรุปหน้าเดียว)" เรียกใช้ซ้ำได้
    คืนค่า (infl_df, None) เมื่อคำนวณได้ หรือ (None, ข้อความเหตุผล) เมื่อคำนวณไม่ได้"""
    influence_vars = [
        v for v in active_lr_vars
        if v != "const" and v in lr_raw_map and v in model_df.columns
    ]
    if len(influence_vars) < 2:
        return None, "ต้องมีตัวแปรอิสระอย่างน้อย 2 ตัวในสมการระยะยาว จึงจะเทียบสัดส่วนอิทธิพลกันได้"
    sample_df = model_df[[dep_ln] + influence_vars].dropna()
    y_std = sample_df[dep_ln].std() if not sample_df.empty else None
    if sample_df.empty or len(sample_df) < 3 or not y_std or pd.isna(y_std):
        return None, "ข้อมูลไม่พอสำหรับคำนวณสัดส่วนอิทธิพล (ต้องการอย่างน้อย 3 ปีที่มีข้อมูลครบทุกตัวแปร)"
    rows = []
    for v in influence_vars:
        x_std = sample_df[v].std()
        if not x_std or pd.isna(x_std) or x_std == 0:
            continue
        std_beta = lr_raw_map[v]["coef"] * (x_std / y_std)
        rows.append({"code": v, "label": _var_full_name(v), "std_beta": std_beta})
    if not rows:
        return None, "ไม่สามารถคำนวณสัดส่วนอิทธิพลได้ (ส่วนเบี่ยงเบนมาตรฐานของตัวแปรบางตัวเป็น 0)"
    infl_df = pd.DataFrame(rows)
    infl_df["abs_beta"] = infl_df["std_beta"].abs()
    total_abs = infl_df["abs_beta"].sum()
    infl_df["สัดส่วน (%)"] = infl_df["abs_beta"] / total_abs * 100
    infl_df["ทิศทาง"] = infl_df["std_beta"].apply(
        lambda x: "ส่งผลเชิงบวก (+)" if x >= 0 else "ส่งผลเชิงลบ (−)"
    )
    infl_df = infl_df.sort_values("สัดส่วน (%)", ascending=False).reset_index(drop=True)
    return infl_df, None

