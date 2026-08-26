"""
================================================================================
TFP - Engle-Granger 2-Step / Restricted Error Correction Model (ECM) Pipeline
================================================================================
เปลี่ยนวิธีจากเวอร์ชันก่อนหน้า (UECM สมการเดียวรวมทุกตัวแปร) มาเป็น
**Engle-Granger 2-step แบบดั้งเดิม** เพราะตารางที่ 2 ที่ สวค. รายงานมา
(ภาพที่ 1) มีลักษณะเป็น 2 สมการแยกกันชัดเจน:
    - สมการระยะยาว (long-run / cointegrating regression): ln(TFPI) กับ
      ตัวแปรที่เหลือรอดหลัง reduction (FDI, FEE, HDI, JOUR, MKTCOM)
    - สมการระยะสั้น (short-run ECM): ผลต่างของตัวแปร (มีบางตัว lag t-1, t-2)
      บวกพจน์ ECM(-1) จาก residual ของสมการระยะยาว

เหตุผลที่เปลี่ยน: การยัด 10-12 ตัวแปรเข้า UECM สมการเดียวพร้อมกันกับ n=22
ปีนั้น "ประมาณค่าไม่ได้ทางคณิตศาสตร์" (พารามิเตอร์ >= observations เสมอ
ไม่ว่าจะตั้ง lag เท่าไหร่) วิธี 2-step นี้ตรงกับโครงสร้างตารางเป้าหมายพอดี
และใช้แค่ statsmodels.OLS ซึ่งเป็น API ที่เสถียรที่สุด ไม่มีปัญหา
attribute-name เปลี่ยนไปมาแบบ UECM/ARDL

================================================================================
CHANGELOG — สรุปทุกจุดที่ตรวจเจอและแก้ระหว่างการไล่เทียบกับตารางที่ 2 ของ สวค.
(อ้างอิงตอนเขียนส่วนวิธีวิจัย/ข้อจำกัดของรายงานได้เลย)
================================================================================
[v1 -> v2] แก้สัญลักษณ์ △ / △² ในตาราง
    - ปัญหาเดิม: โค้ด v1 ตีความ △² ว่าเป็น "first difference ที่ shift 2 คาบ"
      (เหมือน △ ธรรมดา แค่ shift มากกว่า) ทำให้ RDG_GDP/RDP_GDP ผิดเครื่องหมาย
      และผิดขนาดเป็นร้อยเท่าเทียบกับตาราง
    - ยืนยันภายหลังจากเชิงอรรถต้นฉบับ (ที่ตอนแรกถูกตัดขอบภาพไป): "△ และ △²
      หมายถึง ผลต่างลำดับที่ 1 และ 2 ตามลำดับ" -> △² คือ second difference
      จริง (Δ²X_t = X_t - 2X_{t-1} + X_{t-2}) ไม่ใช่ first-diff shift 2 คาบ
    - แก้: แยก diff_order ออกจาก lag ใน SHORT_RUN_SPEC เป็น (col, diff_order, lag)
    - ผล: Adj. R² (ระยะสั้น) กระโดดจาก 0.7895 -> 0.9184

[v2 -> v3] แก้หน่วยตัวแปรที่เป็น % ในไฟล์ Excel
    - ปัญหาเดิม: คอลัมน์ FDI_GDP, RDG_GDP, RDP_GDP, FEE_GDP, TRADE_GDP เก็บเป็น
      หน่วย % (เช่น 3.2 หมายถึง 3.2%) ในไฟล์ Excel ("ข้อมูลตัวชี้วัดและผลิตภาพ.xlsx")
      แต่ตารางเป้าหมายของ สวค. ใช้เป็นสัดส่วนทศนิยม (0.032) ทำให้สัมประสิทธิ์
      ต่างกัน ~74-130 เท่า (ยืนยันจากแถวหน่วยในชีต Data ของไฟล์ต้นฉบับ)
    - แก้: เพิ่ม PERCENT_VARS = ["FDI_GDP","RDG_GDP","RDP_GDP","FEE_GDP",
      "TRADE_GDP"] แล้วหาร 100 ตอนโหลดข้อมูล (load_data) ก่อนทำ log/diff ใดๆ
    - ตรวจสอบแล้วว่า HDI("Index"), RDH_GDP("คนต่อล้านคน"),
      TUM_GDP/JOURN_GDP("รายการ/ล้านบาท"), MKTCOM("Index") ไม่ใช่ % จึงไม่ต้อง
      แก้ (ยืนยันด้วยว่าค่าที่ได้จากตัวแปรกลุ่มนี้ใกล้เคียงตารางเป้าหมายอยู่แล้ว
      ตั้งแต่ก่อนแก้จุดนี้)
    - ผล: Adj. R² ไม่เปลี่ยน (ตามทฤษฎี - linear rescaling ไม่กระทบ fit) แต่
      สัมประสิทธิ์ของ 5 ตัวแปรนี้ขยับเข้าใกล้ตารางเป้าหมายมาก (เช่น FDI_GDP
      ระยะสั้น 0.0071 -> 0.7101 เทียบกับเป้าหมาย 0.6906)

[ตรวจสอบแล้ว - ไม่ใช่สาเหตุของส่วนต่างที่เหลือ]
    - Sample period: ยืนยันจากตารางสรุปสถิติ (ตารางที่ 4.2) ว่าช่วงปีที่ overlap
      ของทุกตัวแปรที่ใช้ในโมเดล = 1999-2020 (n=22) ตรงกับที่ dropna() ตัดได้เอง
      ไม่ต้องแก้อะไร
    - RDG_GDP/RDP_GDP ในชีต Data: เทียบกับชีต RDG_RDP (แหล่งต้นทางในไฟล์เดียวกัน)
      ตรงกันทุกทศนิยมทั้ง 27 ปี (1996-2022) -> ไม่ใช่ data revision ในไฟล์นี้

[ยังไม่ได้แก้ - ต้องข้อมูลเพิ่มเติมจากภายนอกไฟล์]
    - RDH_GDP: ค่าที่ก็อปไว้ในชีต Data ไม่ตรงกับชีต Researcher (OECD/.Stat) ที่มี
      อยู่ในไฟล์ปัจจุบันเลย (อัตราส่วนไม่คงที่ตลอด 26 ปี แม้จะลองหารด้วย GDP
      แล้ว) แสดงว่า RDH_GDP น่าจะอ้างอิงข้อมูล OECD คนละช่วงเวลาการปรับปรุง
      (data vintage) กับที่ สวค. ใช้ตอนทำรายงาน - เป็นข้อจำกัดของการ replicate
      ที่ควรระบุในรายงาน ไม่ใช่จุดที่แก้ในโค้ดหรือใน Excel ได้ (ยังไม่มีข้อมูล
      พอจะรู้ว่าค่าไหน "ถูก" กว่ากัน)
    - ECM(-1), FEE_GDP, TRADE_GDP, MKTCOM, ln_TUM_GDP ยังเบี่ยงจากตารางเป้าหมาย
      เล็กน้อย (ผลจากส่วนต่างสะสมของ RDH_GDP ที่ไหลผ่านสมการระยะยาว/ระยะสั้น)

[v3 -> v4] แก้ sample period ที่ถูกตัดสั้นเกินจำเป็น
    - ปัญหาเดิม: build_model_frame() มี df.dropna(how="any") ที่ตัดทุกแถวซึ่งมี NaN
      ในคอลัมน์ไหนก็ได้จากทั้ง 13 คอลัมน์ดิบ ก่อนที่จะรู้ด้วยซ้ำว่าแต่ละสมการต้องการ
      คอลัมน์ไหนบ้าง ทำให้ปี 2021-2022 หายไปทั้งชุด (เพราะ JOUR_GDP ไม่มีข้อมูลปี
      2021-2022) ทั้งที่สมการระยะสั้นต้องการแค่ JOUR_GDP(-1) ซึ่งใช้ค่าปี 2020 ได้
    - ยืนยันจากภาพหน้าจอ EViews จริง (EQ_LR04_OK, EQ_SR043_OK): Sample ที่ EViews
      ใช้จริงคือ long-run = 1998-2020 (n=23), short-run = 2002-2021 (n=20) - ไม่ใช่
      1999-2020 (n=22) แบบเดิมที่โค้ดคำนวณผิดเพราะ dropna เร็วเกินไป
    - แก้: เอา df.dropna(how="any") ออกจาก build_model_frame() ทั้งหมด ปล่อยให้
      run_long_run()/run_short_run() ทำ .dropna() ของตัวเอง scope เฉพาะคอลัมน์ที่
      สมการนั้น ๆ ใช้จริง (ตรวจสอบแล้วว่าได้ sample ตรงกับ EViews เป๊ะทั้งสองสมการ)
    - ผล: Adj. R² ระยะสั้นขยับจาก 0.9184 -> 0.9183 (แทบไม่เปลี่ยน จุดนี้ไม่ใช่
      ตัวการหลักของส่วนต่างที่เหลือ)

[v4 -> v5] แก้แหล่งข้อมูล RDH_GDP ที่เป็นคนละ data vintage กับที่ สวค. ใช้จริง
    - ปัญหาเดิม: คอลัมน์ RDH_GDP ในชีต "Data" ของไฟล์ Excel ("ข้อมูลตัวชี้วัดและ
      ผลิตภาพ.xlsx") ให้ผลลัพธ์ใกล้เคียงตารางเป้าหมายของ สวค. แต่ไม่ตรงเป๊ะ
      (ต่าง 0.4-9% ในหลายตัวแปรของสมการระยะสั้น โดยเฉพาะ const, FDI_GDP,
      ln_HDI, ln_JOUR_GDP, ln_TUM_GDP, ECM(-1))
    - ตรวจสอบ: เทียบ RDH_GDP ในชีต Data กับชีต "Researcher" (ข้อมูลต้นทาง
      OECD.Stat "researchers per million population" ของประเทศไทย ที่มีอยู่ใน
      ไฟล์เดียวกัน) พบว่าอัตราส่วนระหว่างสองชีตไม่คงที่เลยตลอด 26 ปี (ไล่จาก
      ~4,600 เท่า ในปี 1996 ขึ้นไปเป็น ~16,900 เท่า ในปี 2019) ถ้าเป็นแค่หน่วย/
      มาตราส่วนต่างกัน อัตราส่วนนี้ควรจะคงที่ - จึงสรุปว่าเป็นคนละ data vintage
      กันจริง ไม่ใช่แค่แปลงหน่วย
    - แก้: เปลี่ยนแหล่งข้อมูล RDH_GDP ให้ดึงจากชีต "Researcher" (แถวประเทศไทย,
      ใช้ตัวเลขดิบตรงๆ ไม่ต้องหารด้วย GDP หรือแปลงหน่วยใดๆ เพิ่ม) แทนคอลัมน์
      RDH_GDP เดิมในชีต Data ทั้งหมด (เพิ่มพารามิเตอร์ RDH_SOURCE ใน load_data
      ให้เลือกได้ว่าจะใช้แหล่งไหน ค่า default เปลี่ยนเป็น "researcher")
    - ผล: Adj. R² ระยะสั้น 0.9183 -> **0.9216 ตรงกับ EViews เป๊ะ**
      ตัวแปร 10 จาก 11 ตัวในสมการระยะสั้นตรงกับตาราง EViews (EQ_SR05_OK)
      แบบไม่มีส่วนต่างเลย (const, FDI_GDP, ln_HDI, ln_RDH_GDP, RDP_GDP(-2),
      ln_JOUR_GDP(-1), ln_TUM_GDP(-2), TRADE_GDP(-2), MKTCOM, ECM(-1))
      เหลือ RDG_GDP(-2) ตัวเดียวที่ต่างเล็กน้อย ~0.8% (24.5710 vs 24.7571)

สถานะล่าสุด (v5): Adj. R² ระยะยาว = 0.9701 (ตรงกับ EViews เป๊ะ)
             Adj. R² ระยะสั้น = 0.9216 (ตรงกับ EViews เป๊ะ)
             หมายเหตุ: "0.9629" ในตารางที่ 2 ต้นฉบับคือค่า R-squared ธรรมดา
             ไม่ใช่ Adjusted R-squared (ยืนยันจากภาพหน้าจอ EViews จริงของ
             EQ_SR043_OK: R-squared=0.9629, Adj R-squared=0.9216)
             ตัวแปรระยะสั้นตรงกับ สวค. เกือบทั้งหมด เหลือ RDG_GDP(-2) ที่ยัง
             ต่างเล็กน้อย ~0.8% ซึ่งอาจมาจาก data vintage ของ RDG เช่นกัน แต่
             ผลกระทบน้อยกว่า RDH_GDP มาก

ข้อควรระวัง (สำคัญ - อ่านก่อนใช้):
    1. Engle-Granger 2-step มีข้อเสียเทียบกับ ARDL bounds test ตรงที่ assume
       ว่ามีความสัมพันธ์ระยะยาวแบบเดียว (single cointegrating vector) และ
       long-run coefficient จะมี small-sample bias มากกว่า - ถ้าท้ายที่สุด
       ต้องได้ผลแบบ ARDL bounds test จริง ๆ ต้องกลับไปทำ per-equation ARDL
       ทีละตัวแปรตาม (แนะนำคุยกับ สวค. ว่าเขาใช้ EViews คำสั่งไหนกันแน่
       "Cointegrating Regression" หรือ "ARDL - Automatic Selection")

ติดตั้ง: pip install statsmodels pandas numpy openpyxl scipy
================================================================================
"""

import os
import re
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.diagnostic import het_breuschpagan, acorr_breusch_godfrey
from statsmodels.stats.stattools import jarque_bera

# ------------------------------------------------------------------------------
# 1) CONFIG
# ------------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "."
EXCEL_PATH = os.path.join(SCRIPT_DIR, "ข้อมูลตัวชี้วัดและผลิตภาพ.xlsx")  # แก้ path ถ้าจำเป็น
SHEET_NAME = "Data"

RAW_TO_MODEL = {
    "FDI": "FDI_GDP", "HDI": "HDI", "RDH_GDP": "RDH_GDP", "RDG": "RDG_GDP",
    "RDP": "RDP_GDP", "FEE_GDP": "FEE_GDP", "PATENT_GDP": "PATENT_GDP",
    "TUM_GDP": "TUM_GDP", "PCT_GDP": "PCT_GDP", "JOURN_GDP": "JOUR_GDP",
    "TRADE": "TRADE_GDP", "MKTCOM": "MKTCOM", "TFPI": "TFPI",
}

LOG_VARS = ["HDI", "RDH_GDP", "JOUR_GDP", "PATENT_GDP", "TUM_GDP", "PCT_GDP", "TFPI"]
DEP_VAR = "TFPI"

# --- แหล่งข้อมูล RDH_GDP: "researcher" = ดึงจากชีต Researcher (OECD.Stat, ตรงกับ
# ที่ สวค. ใช้จริง ยืนยันจากการเทียบสัมประสิทธิ์สมการระยะสั้นได้ตรงเป๊ะ), "data" =
# ใช้คอลัมน์ RDH_GDP เดิมในชีต Data (คนละ data vintage กับที่ สวค. ใช้ - เก็บ option
# นี้ไว้เผื่อเทียบ/ตรวจสอบย้อนหลัง)
RDH_SOURCE = "researcher"  # "researcher" | "data"

# --- คอลัมน์ที่เก็บในไฟล์ Excel เป็น % (เช่น 3.2 หมายถึง 3.2%) แต่ตารางเป้าหมาย
# ของ สวค. ใช้เป็นสัดส่วนทศนิยม (0.032) — ยืนยันจากแถวหน่วยในชีตต้นฉบับ:
# FDI, RDG, RDP, FEE_GDP, TRADE = "%"  ส่วน HDI("Index"), RDH_GDP("คนต่อล้านคน"),
# TUM_GDP/JOURN_GDP("รายการ/ล้านบาท") ไม่ใช่ % จึงไม่ต้องแปลง
# ตรวจสอบ MKTCOM เพิ่มเติมด้วยว่าเป็น % หรือไม่ ถ้าใช่ให้เพิ่มชื่อเข้า list นี้
PERCENT_VARS = ["FDI_GDP", "RDG_GDP", "RDP_GDP", "FEE_GDP", "TRADE_GDP"]

# --- ตัวแปรในสมการระยะยาว (จากคอลัมน์ "ค่าสัมประสิทธิ์สมการระยะยาว" ในตารางที่ 2) ---
LONG_RUN_VARS = ["FDI_GDP", "FEE_GDP", "ln_HDI", "ln_JOUR_GDP", "MKTCOM"]

# --- ตัวแปรในสมการระยะสั้น: (ชื่อคอลัมน์, diff_order, lag) ---
# diff_order=1 -> ΔX_t = X_t - X_{t-1}      (สัญลักษณ์ △ ในตาราง)
# diff_order=2 -> Δ²X_t = X_t - 2X_{t-1} + X_{t-2}   (สัญลักษณ์ △² ในตาราง — เป็นคนละ
#                 ตัวกับ "diff แล้ว shift 2 คาบ" ที่เวอร์ชันก่อนหน้าใช้!)
# lag=0 ไม่มี (t-k) กำกับ, lag=1 คือ (t-1), lag=2 คือ (t-2) ของ "ผลต่างที่ระบุ order แล้ว"
#
# แก้จากเวอร์ชันก่อนหน้า: RDH_GDP / RDG_GDP / RDP_GDP มีสัญลักษณ์ △² ในตารางต้นฉบับ
# (ไม่ใช่ △ shift 2 คาบ) — ถ้าตีความผิดจุดนี้ ค่าสัมประสิทธิ์จะเพี้ยนไปมาก (พบว่า
# RDG_GDP/RDP_GDP ที่รันได้ต่างจากตารางเป้าหมายเป็นร้อยเท่าและกลับเครื่องหมาย)
SHORT_RUN_SPEC = [
    ("FDI_GDP", 1, 0),
    ("ln_HDI", 1, 0),
    ("ln_RDH_GDP", 2, 0),
    ("RDG_GDP", 2, 2),
    ("RDP_GDP", 2, 2),
    ("ln_JOUR_GDP", 1, 1),
    ("ln_TUM_GDP", 1, 2),
    ("TRADE_GDP", 1, 2),
    ("MKTCOM", 1, 0),
]


# ------------------------------------------------------------------------------
# 2) โหลด + เตรียมข้อมูล
# ------------------------------------------------------------------------------
def load_researcher_rdh(path: str, country: str = "Thailand") -> pd.Series:
    """ดึง RDH_GDP (researchers per million population) จากชีต 'Researcher'
    (แหล่งต้นทาง OECD.Stat ในไฟล์เดียวกัน) เป็นทางเลือกแทนคอลัมน์ RDH_GDP ใน
    ชีต Data ซึ่งเป็นคนละ data vintage กับที่ สวค. ใช้จริง (ดู [v4 -> v5] ใน
    changelog ด้านบน) ใช้ตัวเลขดิบตรงๆ ไม่ต้องแปลงหน่วยเพิ่ม"""
    res = pd.read_excel(path, sheet_name="Researcher", header=None)
    row = res[res[0].astype(str).str.contains(country, na=False)].iloc[0]
    years = list(range(1996, 2023))  # ตรงกับหัวคอลัมน์ปีในชีต Researcher
    vals = pd.to_numeric(pd.Series(row.values[2:2 + len(years)], index=years),
                          errors="coerce")
    return vals.rename("RDH_GDP")


def load_data(path: str, sheet: str, rdh_source: str = RDH_SOURCE) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=sheet, header=0, skiprows=[1, 2])
    raw = raw.rename(columns={raw.columns[0]: "year"})
    raw = raw.rename(columns=RAW_TO_MODEL)
    raw["year"] = raw["year"].astype(int)
    raw = raw.set_index("year")
    keep = [c for c in RAW_TO_MODEL.values() if c in raw.columns]
    df = raw[keep].copy()
    for col in PERCENT_VARS:
        if col in df.columns:
            df[col] = df[col] / 100.0

    if rdh_source == "researcher":
        rdh = load_researcher_rdh(path)
        df["RDH_GDP"] = rdh.reindex(df.index)
    elif rdh_source != "data":
        raise ValueError('rdh_source ต้องเป็น "researcher" หรือ "data"')
    return df


def build_model_frame(df: pd.DataFrame) -> pd.DataFrame:
    """แก้จากเวอร์ชันก่อนหน้า: เดิมมี df.dropna(how='any') ตรงนี้ ซึ่งตัดทุกแถวที่มี
    NaN ในคอลัมน์ไหนก็ได้จากทั้ง 13 คอลัมน์ - ทำให้ปี 2021-2022 หายไปทั้งที่จริง ๆ
    สมการระยะสั้นต้องการแค่ JOUR_GDP(-1) (ใช้ค่าปี 2020 ได้อยู่แล้ว ไม่ต้องมี
    JOUR_GDP ปี 2021) EViews ไม่ตัดข้อมูลแบบนี้ - แต่ละสมการ (View->Sample adjusted)
    ใช้ช่วงปีที่ตัวมันเองต้องการเท่านั้น ตอนนี้เปลี่ยนมาไม่ dropna ที่นี่เลย
    ปล่อยให้ run_long_run()/run_short_run() ทำ .dropna() ของตัวเองซึ่ง scope
    เฉพาะคอลัมน์ที่แต่ละสมการใช้จริงอยู่แล้ว (ผลคือ long-run ได้ 1998-2020 n=23,
    short-run ได้ 2002-2021 n=20 ตรงกับ EViews เป๊ะ)"""
    df = df.copy()
    for col in LOG_VARS:
        if col in df.columns:
            invalid = (df[col] <= 0) & df[col].notna()
            if invalid.any():
                raise ValueError(f"ตัวแปร {col} มีค่า <= 0 ทำ log ไม่ได้")
            df["ln_" + col] = np.log(df[col])
    return df


def adf_report(series: pd.Series, name: str) -> dict:
    level_stat, level_p, *_ = adfuller(series.dropna(), autolag="AIC")
    diff_stat, diff_p, *_ = adfuller(series.diff().dropna(), autolag="AIC")
    order = "I(0)" if level_p < 0.05 else ("I(1)" if diff_p < 0.05 else "I(2)?")
    return {"variable": name, "adf_level_p": round(level_p, 4),
            "adf_diff_p": round(diff_p, 4), "order_of_integration": order}


def summary_adj_r2(res) -> float:
    """ดึง Adj. R-squared แบบทนทานต่อการเปลี่ยน attribute ระหว่างเวอร์ชัน"""
    if hasattr(res, "rsquared_adj"):
        try:
            return float(res.rsquared_adj)
        except Exception:
            pass
    r2, n, k = float(res.rsquared), float(res.nobs), len(res.params)
    return 1 - (1 - r2) * (n - 1) / (n - k - 1)


# ------------------------------------------------------------------------------
# 3) STEP 1 - สมการระยะยาว (Cointegrating regression) + Engle-Granger test
# ------------------------------------------------------------------------------
def run_long_run(df: pd.DataFrame, dep: str, long_run_vars: list):
    sub = df[[dep] + long_run_vars].dropna()
    X = add_constant(sub[long_run_vars])
    model = OLS(sub[dep], X)
    res = model.fit()

    print("\n=== STEP 1: สมการระยะยาว (Long-run / Cointegrating Regression) ===")
    print(f"Sample ที่ใช้จริง: {sub.index.min()}-{sub.index.max()}  (n={len(sub)})")
    print(res.summary())
    print(f"\nAdj. R^2 (ระยะยาว) = {summary_adj_r2(res):.4f}")

    # Engle-Granger cointegration test: ADF บน residual (ต้อง reject unit root
    # ถึงจะสรุปว่า cointegrate กันจริง - ค่าวิกฤตของ EG ต่างจาก ADF ปกติเล็กน้อย
    # แต่ใช้ ADF ธรรมดาเป็น first-pass check ได้)
    resid = res.resid
    adf_stat, adf_p, *_ = adfuller(resid, autolag="AIC")
    print(f"\nEngle-Granger residual ADF test: stat={adf_stat:.4f}, p={adf_p:.4f}")
    if adf_p < 0.10:
        print("-> residual น่าจะ stationary (มี cointegration) แม้ p อาจไม่ต่ำมาก "
              "เพราะค่าวิกฤต EG ต่างจาก ADF ปกติ (โดยทั่วไปเข้มกว่า)")
    else:
        print("-> residual ยัง non-stationary ตาม ADF ธรรมดา - ควรระวัง อาจไม่ cointegrate จริง "
              "(ลองปรับตัวแปรใน LONG_RUN_VARS หรือใช้ EG critical value ตาราง MacKinnon)")

    return res, resid


# ------------------------------------------------------------------------------
# 4) STEP 2 - สมการระยะสั้น (Restricted ECM) โดยใช้ residual จาก STEP 1 เป็น ECM(-1)
# ------------------------------------------------------------------------------
def build_diff_regressor(series: pd.Series, diff_order: int, lag: int) -> pd.Series:
    """สร้างผลต่างของ X ตาม diff_order (1=△, 2=△²) แล้วเลื่อน (shift) ไป lag คาบ
    หมายเหตุ: diff_order=2 คือ second difference จริง ๆ (X_t - 2X_{t-1} + X_{t-2}),
    ไม่ใช่ first difference ที่ shift 2 คาบ — คนละตัวกัน อย่าสลับกัน"""
    d = series.diff(diff_order)  # pandas: .diff(2) = X_t - X_{t-2}, NOT true 2nd diff!
    if diff_order == 2:
        d = series.diff().diff()  # true second difference
    return d.shift(lag)


def run_short_run(df: pd.DataFrame, dep: str, short_run_spec: list,
                   long_run_resid: pd.Series):
    dep_diff = df[dep].diff()
    ecm_lag1 = long_run_resid.reindex(df.index).shift(1)

    reg_df = pd.DataFrame({"d_" + dep: dep_diff, "ECM_lag1": ecm_lag1})
    for col, diff_order, lag in short_run_spec:
        reg_df[f"d{diff_order}_{col}_lag{lag}"] = build_diff_regressor(df[col], diff_order, lag)

    reg_df = reg_df.dropna(how="any")
    y = reg_df["d_" + dep]
    X = add_constant(reg_df.drop(columns=["d_" + dep]))

    n_params = X.shape[1]
    print(f"\n=== STEP 2: สมการระยะสั้น (Restricted ECM) ===")
    print(f"Sample ที่ใช้จริง: {reg_df.index.min()}-{reg_df.index.max()}  (n={len(reg_df)})")
    print(f"จำนวนพารามิเตอร์: {n_params}  |  observations ที่ใช้ได้: {len(reg_df)}")
    if n_params >= len(reg_df):
        print("!! พารามิเตอร์ >= observations - ต้องตัดตัวแปรใน SHORT_RUN_SPEC ออกบางตัว")
        return None

    res = OLS(y, X).fit()
    print(res.summary())
    print(f"\nAdj. R^2 (ระยะสั้น) = {summary_adj_r2(res):.4f}")

    ecm_coef = res.params.get("ECM_lag1", np.nan)
    ecm_p = res.pvalues.get("ECM_lag1", np.nan)
    print(f"\nสัมประสิทธิ์ ECM(-1) = {ecm_coef:.4f} (p={ecm_p:.4f})")
    if ecm_coef < 0 and ecm_p < 0.05:
        print("-> ECM(-1) ติดลบและ significant: สอดคล้องกับทฤษฎี ECM (ปรับเข้าสู่ดุลยภาพระยะยาว)")
    else:
        print("-> ECM(-1) ไม่ติดลบ หรือไม่ significant: ผิดจากที่ทฤษฎี ECM คาดไว้ ต้องทบทวนสเปก")

    return res


# ------------------------------------------------------------------------------
# 4b) DIAGNOSTICS — ตารางตรวจสอบข้อสมมติฐานของแบบจำลอง (assumption checks)
# ------------------------------------------------------------------------------
# *** คำเตือนสำคัญ (อ่านก่อนใช้) ***
# ตารางนี้คือ "สัญญาณเตือนเบื้องต้นสำหรับผู้ทำวิจัย" เท่านั้น ไม่ใช่ "คำตัดสินสุดท้าย"
# ของความถูกต้องทางสถิติ — ห้ามอ่านแค่สถานะเขียว/แดงแล้วสรุปทันทีโดยไม่เข้าใจนัยของ
# การทดสอบแต่ละตัว เกณฑ์ผ่าน/ไม่ผ่านที่ใช้ (เช่น VIF > 10, p < 0.05) เป็น "กฎยางงาน"
# (rule of thumb) ที่นิยมใช้กันทั่วไป ไม่ใช่กฎตายตัวทางทฤษฎี — ผลลัพธ์ระดับก้ำกึ่ง
# (เช่น p ~ 0.08, ln(x)? I(2)) จะได้สถานะกลาง "ต้องพิจารณาเพิ่มเติม/ก้ำกึ่ง" แทนที่จะ
# ถูกบังคับให้เป็นแค่ผ่าน/ไม่ผ่านสองสถานะ ทุกแถวควรอ่านคู่กับคอลัมน์ "หมายเหตุ" และ
# ควรปรึกษาผู้เชี่ยวชาญด้านเศรษฐมิติก่อนใช้เป็นข้อสรุปในรายงานฉบับจริง

_STATUS_PASS = "🟢 ผ่าน"
_STATUS_WATCH = "🟡 ต้องพิจารณาเพิ่มเติม"
_STATUS_BORDERLINE = "🟡 ก้ำกึ่ง"
_STATUS_FAIL = "🔴 ไม่ผ่าน"


def _diag_row(category: str, item: str, result: str, status: str, note: str = "") -> dict:
    return {"หมวด": category, "รายการ": item, "ผลลัพธ์": result, "สถานะ": status, "หมายเหตุ": note}


def _stationarity_rows(df: pd.DataFrame, variables: list) -> list:
    """ทดสอบ order of integration (ADF) ของตัวแปรที่เข้าสมการระยะยาว (รวมตัวแปรตาม)
    แล้วเทียบว่าตัวไหน "ไม่สอดคล้อง" กับ order ที่พบมากที่สุดในกลุ่ม — ตามทฤษฎี
    cointegration ตัวแปรที่จะ cointegrate กันควรมี order เดียวกัน (โดยทั่วไป I(1))"""
    reports = [adf_report(df[v], v) for v in dict.fromkeys(variables) if v in df.columns]
    orders = [r["order_of_integration"] for r in reports]
    majority = max(set(orders), key=orders.count) if orders else None
    rows = []
    for r in reports:
        order = r["order_of_integration"]
        if order == "I(2)?":
            status = _STATUS_WATCH
            note = "ลำดับความนิ่งไม่ชัดเจน (p ทั้งที่ระดับและที่ผลต่างยังสูงกว่า 0.05)"
        elif order != majority:
            status = _STATUS_WATCH
            note = f"ตัวแปรอื่นในสมการส่วนใหญ่เป็น {majority} ไม่สอดคล้องกัน"
        else:
            status, note = _STATUS_PASS, ""
        rows.append(_diag_row("Stationarity", r["variable"], order, status, note))
    return rows


def _stationarity_short_run_rows(df: pd.DataFrame, short_run_spec: list) -> list:
    """ตรวจ stationarity ของตัวแปรฝั่งขวาที่ใช้ในสมการระยะสั้น (Restricted ECM) ตาม
    active_sr_spec จริงจากหน้าเว็บ — ถ้าผู้ใช้ปรับตัวแปร short-run ใน UI ผลตรงนี้จะ
    เปลี่ยนตามตัวแปรที่เลือกด้วย (ไม่ใช่ SHORT_RUN_SPEC ตายตัวจากไฟล์โค้ด)

    ตรวจ 2 รอบต่อตัวแปร (ตัดตัวแปรซ้ำถ้ามี base column เดียวกันมากกว่าหนึ่งสเปก):
      (1) ตัวแปรต้นฉบับ (ก่อนแปลง) — ผ่าน adf_report() ตัวเดิม ว่าเป็น I(0)/I(1)/I(2)?
      (2) ตัวแปรหลัง Transformation ตามสเปกจริงที่ใช้ในสมการ (Δ หรือ Δ² พร้อม lag ถ้ามี)
          ผ่าน build_diff_regressor() ตัวเดิมที่ run_short_run() ใช้สร้าง regressor จริง
          แล้วทดสอบ ADF ตรง ๆ ว่าตัวแปรหลังแปลงนิ่ง (stationary) หรือไม่

    ไม่แตะ/ไม่เปลี่ยนพฤติกรรมของ _stationarity_rows(), _cointegration_row() หรือ
    การตรวจ Long-run เดิม — เพิ่มเป็นหมวดใหม่ "Stationarity (Short-run)" เท่านั้น"""
    rows: list = []
    seen_cols = set()
    for col, diff_order, lag in short_run_spec:
        if col not in df.columns or col in seen_cols:
            continue
        seen_cols.add(col)
        diff_symbol = "Δ" if diff_order == 1 else "Δ²"
        lag_suffix = f" (t-{lag})" if lag else ""

        # (1) ตัวแปรต้นฉบับ — I(0)/I(1)/I(2)? เหมือน _stationarity_rows() เดิม
        try:
            r_raw = adf_report(df[col], col)
            order_raw = r_raw["order_of_integration"]
            status_raw = _STATUS_WATCH if order_raw == "I(2)?" else _STATUS_PASS
            note_raw = f"สเปกปัจจุบันแปลงด้วย {diff_symbol}{lag_suffix} ก่อนเข้าสมการระยะสั้น"
        except Exception as e:
            order_raw, status_raw = "n/a", _STATUS_WATCH
            note_raw = f"คำนวณไม่ได้: {e}"
        rows.append(_diag_row("Stationarity (Short-run)", col, order_raw, status_raw, note_raw))

        # (2) ตัวแปรหลัง Transformation ตามสเปกจริง (Δ หรือ Δ² + lag) ว่านิ่งหรือไม่
        item_label = f"{diff_symbol}{col}{lag_suffix}"
        try:
            transformed = build_diff_regressor(df[col], diff_order, lag).dropna()
            if len(transformed) < 4:
                raise ValueError("ข้อมูลไม่พอสำหรับทดสอบ ADF (n<4 หลัง transform+lag)")
            _, p_t, *_ = adfuller(transformed, autolag="AIC")
            if p_t < 0.05:
                status_t, note_t = _STATUS_PASS, ""
            elif p_t < 0.10:
                status_t = _STATUS_BORDERLINE
                note_t = "นิ่งที่ระดับ 10% แต่ไม่นิ่งที่ 5%"
            else:
                status_t = _STATUS_FAIL
                note_t = f"หลังแปลงด้วย {diff_symbol} แล้วยัง non-stationary ตาม ADF — diff_order ในสเปกอาจไม่พอ"
            result_t = f"p={p_t:.3f}"
        except Exception as e:
            status_t, note_t, result_t = _STATUS_WATCH, f"คำนวณไม่ได้: {e}", "n/a"
        rows.append(_diag_row("Stationarity (Short-run)", item_label, result_t, status_t, note_t))
    return rows


def _cointegration_row(resid: pd.Series) -> dict:
    """Engle-Granger residual test: ADF บน residual ของสมการระยะยาว ต้อง reject
    unit root (p ต่ำ) ถึงจะสรุปว่ามี cointegration จริง — หมายเหตุ: ค่าวิกฤตที่ถูกต้อง
    ของ EG ต่างจาก ADF ปกติเล็กน้อย (เข้มกว่า) นี่เป็นการเช็คแบบ first-pass เท่านั้น"""
    adf_stat, adf_p, *_ = adfuller(resid.dropna(), autolag="AIC")
    if adf_p < 0.05:
        status, note = _STATUS_PASS, ""
    elif adf_p < 0.10:
        status = _STATUS_BORDERLINE
        note = "ผ่านที่ระดับ 10% แต่ไม่ผ่านที่ 5% — ควรตรวจสอบด้วยค่าวิกฤต MacKinnon จริง"
    else:
        status = _STATUS_FAIL
        note = "residual ยัง non-stationary ตาม ADF ธรรมดา (ค่าวิกฤต EG จริงเข้มกว่านี้ ควรตรวจซ้ำ)"
    return _diag_row("Cointegration", "Engle-Granger residual", f"p={adf_p:.3f}", status, note)


def _multicollinearity_rows(df: pd.DataFrame, variables: list) -> list:
    """VIF ของตัวแปรอิสระในสมการระยะยาว + รายงานคู่ตัวแปรที่สหสัมพันธ์สูงสุด
    เมื่อ VIF เริ่มสูง (ช่วยตีความว่า "สูงเพราะคู่กับตัวไหน")"""
    sub = df[list(dict.fromkeys(variables))].dropna()
    X = add_constant(sub)
    corr = sub.corr()
    rows = []
    for i, v in enumerate(sub.columns):
        vif = variance_inflation_factor(X.values, i + 1)  # +1 เพื่อข้าม const
        if vif > 10:
            status = _STATUS_FAIL
        elif vif > 5:
            status = _STATUS_WATCH
        else:
            status = _STATUS_PASS
        note = ""
        if vif > 5 and len(sub.columns) > 1:
            partner = corr[v].drop(v).abs().idxmax()
            note = f"r={corr.loc[v, partner]:.3f} กับ {partner}"
        rows.append(_diag_row("Multicollinearity", v, f"VIF={vif:.1f}", status, note))
    return rows


def _heteroskedasticity_row(res, label: str) -> dict:
    """Breusch-Pagan test: H0 = ไม่มี heteroskedasticity (ผ่าน = p สูง)"""
    lm_stat, lm_p, f_stat, f_p = het_breuschpagan(res.resid, res.model.exog)
    if lm_p >= 0.05:
        status, note = _STATUS_PASS, ""
    elif lm_p >= 0.01:
        status = _STATUS_WATCH
        note = "นัยสำคัญไม่สูงมาก ควรตรวจสอบเพิ่มเติมก่อนสรุป"
    else:
        status = _STATUS_FAIL
        note = "มีแนวโน้ม heteroskedastic — พิจารณาใช้ robust/HC standard error"
    return _diag_row("Heteroskedasticity", f"Breusch-Pagan ({label})", f"p={lm_p:.3f}", status, note)


def _autocorrelation_row(res, label: str, nlags: int = 1) -> dict:
    """Breusch-Godfrey test: H0 = ไม่มี autocorrelation หลงเหลือ (ผ่าน = p สูง)"""
    bg_stat, bg_p, f_stat, f_p = acorr_breusch_godfrey(res, nlags=nlags)
    if bg_p >= 0.10:
        status, note = _STATUS_PASS, ""
    elif bg_p >= 0.05:
        status = _STATUS_BORDERLINE
        note = "ผ่านที่ระดับ 5% แต่ไม่ผ่านที่ 10%"
    else:
        status = _STATUS_FAIL
        note = "มีแนวโน้ม autocorrelation หลงเหลือในค่าคลาดเคลื่อน"
    return _diag_row("Autocorrelation", f"Breusch-Godfrey ({label}, lag={nlags})",
                      f"p={bg_p:.3f}", status, note)


def _normality_row(res, label: str) -> dict:
    """Jarque-Bera test: H0 = ค่าคลาดเคลื่อนแจกแจงแบบปกติ (ผ่าน = p สูง)"""
    jb_stat, jb_p, skew, kurtosis = jarque_bera(res.resid)
    if jb_p >= 0.05:
        status, note = _STATUS_PASS, ""
    else:
        status = _STATUS_WATCH
        note = "ค่าคลาดเคลื่อนอาจไม่แจกแจงแบบปกติ (ตัวอย่างเล็ก ยังพอใช้ผลได้แต่ควรระวังการอนุมาน)"
    return _diag_row("Normality", f"Jarque-Bera ({label})", f"p={jb_p:.3f}", status, note)


def run_diagnostics(model_df: pd.DataFrame, dep_ln: str, long_run_vars: list,
                     lr_res, sr_res, lr_resid: pd.Series,
                     short_run_spec: list | None = None) -> pd.DataFrame:
    """รวมผลตรวจสอบข้อสมมติฐาน (assumption checks) ของสมการระยะยาว/ระยะสั้นทั้งหมด
    เป็นตารางเดียว คืนค่าเป็น DataFrame คอลัมน์: หมวด, รายการ, ผลลัพธ์, สถานะ, หมายเหตุ

    short_run_spec: ถ้าใส่เข้ามา (เช่น active_sr_spec จากหน้าเว็บ) จะเพิ่มหมวด
    "Stationarity (Short-run)" ต่อจาก Stationarity เดิม — ตรวจตัวแปรระยะสั้นทุกตัวที่
    ใช้งานจริงทั้งก่อนและหลัง transform ตามสเปกจริง ถ้าไม่ใส่ (None) จะข้ามหมวดนี้ไป
    เหมือนพฤติกรรมเดิมของฟังก์ชัน (ไม่กระทบ Long-run/Cointegration/ECM/Diagnostics อื่น)

    *** สำคัญ ***: นี่คือสัญญาณเตือนเบื้องต้น ไม่ใช่คำตัดสินสุดท้าย — อ่านคำเตือน
    ที่ต้นหัวข้อ "4b) DIAGNOSTICS" ด้านบนก่อนนำผลไปอ้างอิงในรายงาน"""
    rows: list = []
    rows += _stationarity_rows(model_df, [dep_ln] + list(long_run_vars))
    if short_run_spec:
        rows += _stationarity_short_run_rows(model_df, short_run_spec)
    rows.append(_cointegration_row(lr_resid))
    rows += _multicollinearity_rows(model_df, long_run_vars)
    rows.append(_heteroskedasticity_row(lr_res, "สมการระยะยาว"))
    rows.append(_autocorrelation_row(lr_res, "สมการระยะยาว"))
    rows.append(_normality_row(lr_res, "สมการระยะยาว"))
    if sr_res is not None:
        rows.append(_heteroskedasticity_row(sr_res, "สมการระยะสั้น"))
        rows.append(_autocorrelation_row(sr_res, "สมการระยะสั้น"))
        rows.append(_normality_row(sr_res, "สมการระยะสั้น"))
    return pd.DataFrame(rows, columns=["หมวด", "รายการ", "ผลลัพธ์", "สถานะ", "หมายเหตุ"])


# ------------------------------------------------------------------------------
# 5) Helper: แปลงผลลัพธ์เป็นตาราง (ใช้ต่อใน app.py สำหรับหน้าเว็บ)
# ------------------------------------------------------------------------------
def build_coefficient_tables(lr_res, sr_res) -> tuple[pd.DataFrame, pd.DataFrame]:
    """แปลงผลลัพธ์ statsmodels ของสมการระยะยาว/ระยะสั้นเป็นตาราง pandas
    ที่พร้อมแปะลง prompt หรือแสดงบนหน้าเว็บได้ตรง ๆ"""
    lr_table = pd.DataFrame({
        "ตัวแปร": lr_res.params.index,
        "ค่าสัมประสิทธิ์": lr_res.params.values.round(4),
        "p-value": lr_res.pvalues.values.round(4),
    })
    sr_table = pd.DataFrame({
        "ตัวแปร": sr_res.params.index,
        "ค่าสัมประสิทธิ์": sr_res.params.values.round(4),
        "p-value": sr_res.pvalues.values.round(4),
    })
    return lr_table, sr_table


def stars_from_p(p) -> str:
    """แปลง p-value เป็นสัญลักษณ์ดาวบอกนัยสำคัญ (*, **, ***) ตามธรรมเนียมตาราง
    ที่ระดับความเชื่อมั่น 90% / 95% / 99% ตามลำดับ"""
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return ""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


# --- ลำดับแถว + ชื่อภาษาไทย + สัญลักษณ์ผลต่าง (△/△²) ให้ตรงกับตารางต้นฉบับของ
# สวค. (ภาพที่ 2) เรียงตามลำดับที่ปรากฏในตารางจริงเป๊ะ ๆ ตัวแปรที่ไม่ได้อยู่ใน
# LONG_RUN_VARS/SHORT_RUN_SPEC ของโมเดลปัจจุบัน (PCT, PATENT, INDUS) จะแสดงเป็น
# "-" ทั้งสองคอลัมน์ (คงแถวไว้เพื่อให้โครงตารางตรงกับต้นฉบับ)
ROW_ORDER = [
    ("const", "ค่าคงที่ : c", None),
    ("FDI_GDP", "การลงทุนโดยตรงจากต่างประเทศ : FDI/GDP", "△"),
    ("FEE_GDP", "สัดส่วนค่าธรรมเนียมในการใช้ทรัพย์สินทางปัญญาต่อ GDP : FEE/GDP", "△"),
    ("ln_HDI", "การพัฒนามนุษย์ : ln(HDI)", "△"),
    ("ln_RDH_GDP", "บุคลากรด้าน R&D : ln(RDH/GDP)", "△²"),
    ("RDG_GDP", "การลงทุน R&D ของรัฐ : RDG/GDP", "△²"),
    ("RDP_GDP", "การลงทุน R&D ของเอกชน : RDP/GDP", "△²"),
    ("ln_JOUR_GDP", "สิ่งพิมพ์ทางวิทยาศาสตร์ฯ : ln(JOUR/GDP)", "△"),
    ("ln_PCT_GDP", "สนธิสัญญาความร่วมมือด้านสิทธิบัตร : ln(PCT/GDP)", "△"),
    ("ln_PATENT_GDP", "สิทธิบัตร : ln(PATENT/GDP)", "△"),
    ("ln_TUM_GDP", "อนุสิทธิบัตร : ln(TUM/GDP)1", "△"),
    ("INDUS_GDP", "มูลค่าเพิ่มภาคอุตสาหกรรม : INDUS/GDP", "△"),
    ("TRADE_GDP", "การเปิดกว้างทางการค้า : TRADE/GDP", "△"),
    ("MKTCOM", "ความซับซ้อนทางเศรษฐกิจ : MKTCOM", "△"),
    ("ECM_lag1", "ECM", None),
]

# --- ชื่อ column จริงในผลลัพธ์สมการระยะสั้น (statsmodels) + lag ของแต่ละตัวแปร
# สร้างจาก SHORT_RUN_SPEC โดยอัตโนมัติ ไม่ต้อง maintain ซ้ำสองที่ ---
SHORT_RUN_LOOKUP = {
    col: (f"d{diff_order}_{col}_lag{lag}", lag)
    for col, diff_order, lag in SHORT_RUN_SPEC
}


def _long_run_cell(lr_res, key: str) -> str:
    if key is None or key not in lr_res.params.index:
        return "-"
    return f"{lr_res.params[key]:.4f}"


def _short_run_cell(sr_res, key: str):
    """คืนค่า (ข้อความค่าสัมประสิทธิ์พร้อม lag นำหน้า, ดาวนัยสำคัญ)"""
    if key in ("const", "ECM_lag1"):
        pname, lag = key, 0
    elif key in SHORT_RUN_LOOKUP:
        pname, lag = SHORT_RUN_LOOKUP[key]
    else:
        return "-", ""
    if pname not in sr_res.params.index:
        return "-", ""
    coef = sr_res.params[pname]
    p = sr_res.pvalues[pname]
    lag_prefix = f"(t-{lag}) " if lag else ""
    return f"{lag_prefix}{coef:.4f}", stars_from_p(p)


def build_target_style_table(lr_res, sr_res) -> pd.DataFrame:
    """สร้างตารางเดียวรวมระยะยาว+ระยะสั้น ให้มีรูปแบบตรงกับตารางที่ 2 ต้นฉบับของ
    สวค. (คอลัมน์: ตัวแปร, ค่าสัมประสิทธิ์ระยะยาว, ค่าสัมประสิทธิ์ระยะสั้น(พร้อมดาว
    และ lag), หมายเหตุ(△/△²)) ใช้ทั้งแสดงบนเว็บ (Streamlit) และไปออก PDF"""
    rows = []
    for key, label, symbol in ROW_ORDER:
        if key == "ECM_lag1":
            lr_val = "n.a."
        else:
            lr_val = _long_run_cell(lr_res, key)
        sr_val, sr_stars = _short_run_cell(sr_res, key)
        rows.append({
            "ตัวแปร": label,
            "ระยะยาว": lr_val,
            "ระยะสั้น": sr_val,
            "นัยสำคัญ": sr_stars,
            "หมายเหตุ": symbol or "",
        })
    rows.append({
        "ตัวแปร": "Adj. R²",
        "ระยะยาว": f"{summary_adj_r2(lr_res):.4f}",
        "ระยะสั้น": f"{summary_adj_r2(sr_res):.4f}",
        "นัยสำคัญ": "",
        "หมายเหตุ": "",
    })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------
# 5b) Helper: เรนเดอร์ตารางข้างบนเป็น HTML สไตล์กรมน้ำเงิน-ทอง ให้หน้าตาใกล้เคียง
# ตารางต้นฉบับของ สวค. เมื่อแสดงบน Streamlit (st.markdown(html, unsafe_allow_html=True))
# ------------------------------------------------------------------------------
def render_target_style_table_html(table: pd.DataFrame, title: str = "") -> str:
    header_bg = "#0B2E52"
    header_fg = "#F5B800"
    row_bg_a = "#0F3A66"
    row_bg_b = "#0B2E52"
    border = "#1C4A78"
    text_fg = "#FFFFFF"
    footer_bg = "#F5B800"   # แถว Adj. R² ไฮไลต์พื้นทองให้เด่นแยกจากแถวอื่น
    footer_fg = "#0B2E52"
    pos_fg = "#4ADE80"      # ค่าสัมประสิทธิ์เป็นบวก -> เขียว
    neg_fg = "#F87171"      # ค่าสัมประสิทธิ์เป็นลบ -> แดง

    def esc(v):
        return str(v).replace("<", "&lt;").replace(">", "&gt;")

    def value_color(v: str) -> str:
        """คืนสีตามเครื่องหมายของค่าตัวเลข ('-'/'n.a.' หรือ parse ไม่ได้ -> สีปกติ)"""
        s = str(v).strip()
        try:
            num = float(s)
        except ValueError:
            return text_fg
        if num > 0:
            return pos_fg
        if num < 0:
            return neg_fg
        return text_fg

    thead = f"""
    <tr>
      <th style="background:{header_bg};color:{header_fg};padding:10px;border:1px solid {border};text-align:left;">ตัวแปร</th>
      <th style="background:{header_bg};color:{header_fg};padding:10px;border:1px solid {border};">ค่าสัมประสิทธิ์สมการระยะยาว</th>
      <th style="background:{header_bg};color:{header_fg};padding:10px;border:1px solid {border};">ค่าสัมประสิทธิ์สมการระยะสั้น</th>
    </tr>"""

    body_rows = []
    n = len(table)
    for i, row in table.iterrows():
        is_footer = row["ตัวแปร"] == "Adj. R²"
        bg = footer_bg if is_footer else (row_bg_a if i % 2 == 0 else row_bg_b)
        fg = footer_fg if is_footer else text_fg
        lr_fg = footer_fg if is_footer else value_color(row["ระยะยาว"])
        sr_fg = footer_fg if is_footer else value_color(row["ระยะสั้น"])

        sr_text = esc(row["ระยะสั้น"])
        if row["นัยสำคัญ"]:
            star_fg = footer_fg if is_footer else header_fg
            sr_text += f' <b style="color:{star_fg};">{esc(row["นัยสำคัญ"])}</b>'
        if row["หมายเหตุ"]:
            sr_text += f' <span style="opacity:0.8;">{esc(row["หมายเหตุ"])}</span>'
        weight = "700" if is_footer else "400"
        body_rows.append(f"""
        <tr>
          <td style="background:{bg};color:{fg};padding:8px 10px;border:1px solid {border};font-weight:{weight};">{esc(row["ตัวแปร"])}</td>
          <td style="background:{bg};color:{lr_fg};padding:8px 10px;border:1px solid {border};text-align:center;font-weight:{weight};">{esc(row["ระยะยาว"])}</td>
          <td style="background:{bg};color:{sr_fg};padding:8px 10px;border:1px solid {border};text-align:center;font-weight:{weight};">{sr_text}</td>
        </tr>""")

    title_html = f'<div style="color:{header_fg};font-size:1.1rem;font-weight:700;margin-bottom:6px;">{esc(title)}</div>' if title else ""

    return f"""
    {title_html}
    <div style="overflow-x:auto;border-radius:8px;">
    <table style="width:100%;border-collapse:collapse;font-size:0.92rem;">
      <thead>{thead}</thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>
    </div>
    <div style="color:#9fb3c8;font-size:0.75rem;margin-top:6px;">
      หมายเหตุ: ***, **, * หมายถึง นัยสำคัญที่ระดับความเชื่อมั่น 99%, 95%, 90% ตามลำดับ |
      "-" หมายถึงตัวแปรที่ไม่ได้อยู่ในสมการรุ่นนี้ | △ และ △² หมายถึงผลต่างลำดับที่ 1 และ 2 ตามลำดับ |
      <span style="color:{pos_fg};">■</span> ค่าเป็นบวก &nbsp;
      <span style="color:{neg_fg};">■</span> ค่าเป็นลบ
    </div>
    """


def build_tfpi_yoy_summary(model_df: pd.DataFrame, dep_ln: str) -> str:
    """สรุปการเปลี่ยนแปลงของ TFPI (ตัวแปรตาม) ปีล่าสุดเทียบปีก่อนหน้า เป็นข้อความ
    ธรรมดา ให้ LLM ใช้ประกอบ 'ส่วนที่ 2: เปรียบเทียบกับปีที่แล้ว'"""
    series = model_df[dep_ln].dropna()
    if len(series) < 2:
        return "ข้อมูลไม่พอสำหรับเปรียบเทียบปีต่อปี"
    last_year, prev_year = series.index[-1], series.index[-2]
    pct_change = (series.iloc[-1] - series.iloc[-2]) * 100  # log-diff ≈ % change
    return (f"TFPI (log) ปี {prev_year} = {series.iloc[-2]:.4f}, "
            f"ปี {last_year} = {series.iloc[-1]:.4f} "
            f"(เปลี่ยนแปลงประมาณ {pct_change:+.2f}%)")


# ------------------------------------------------------------------------------
# 5c) Helper: สร้างรายงาน PDF (ตาราง + บทสรุปผู้บริหารจาก AI) ด้วย reportlab
# ------------------------------------------------------------------------------
# ต้องมีฟอนต์ไทยวางไว้ที่ SCRIPT_DIR/fonts/Sarabun-Regular.ttf และ
# SCRIPT_DIR/fonts/Sarabun-Bold.ttf ก่อน (ฟอนต์มาตรฐานของ reportlab ไม่มีตัวอักษร
# ไทย) ดาวน์โหลดฟรีได้จาก Google Fonts: https://fonts.google.com/specimen/Sarabun
# (กด "Download family" แล้วก็อปไฟล์ Sarabun-Regular.ttf, Sarabun-Bold.ttf มาวาง)
FONT_DIR = os.path.join(SCRIPT_DIR, "fonts")
FONT_REGULAR_PATH = os.path.join(FONT_DIR, "Sarabun-Regular.ttf")
FONT_BOLD_PATH = os.path.join(FONT_DIR, "Sarabun-Bold.ttf")
THAI_FONT_HELP = (
    "ไม่พบไฟล์ฟอนต์ภาษาไทยสำหรับสร้าง PDF\n"
    f"กรุณาดาวน์โหลดฟอนต์ 'Sarabun' (ฟรี) จาก https://fonts.google.com/specimen/Sarabun "
    f"แล้วนำไฟล์ Sarabun-Regular.ttf และ Sarabun-Bold.ttf ไปวางไว้ที่โฟลเดอร์:\n{FONT_DIR}"
)


def register_thai_fonts():
    """ลงทะเบียนฟอนต์ไทย (Sarabun) กับ reportlab ครั้งเดียว ถ้ายังไม่เคยลงทะเบียน
    เรียกก่อนสร้าง PDF ทุกครั้ง — ถ้าไม่พบไฟล์ฟอนต์จะ raise FileNotFoundError
    พร้อมคำแนะนำวิธีแก้ (ดู THAI_FONT_HELP)"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "Sarabun" in pdfmetrics.getRegisteredFontNames():
        return
    if not (os.path.exists(FONT_REGULAR_PATH) and os.path.exists(FONT_BOLD_PATH)):
        raise FileNotFoundError(THAI_FONT_HELP)
    pdfmetrics.registerFont(TTFont("Sarabun", FONT_REGULAR_PATH))
    pdfmetrics.registerFont(TTFont("Sarabun-Bold", FONT_BOLD_PATH))


def _markdown_line_to_paragraph(line: str, styles) -> "object | None":
    """แปลง 1 บรรทัดข้อความ (markdown อย่างง่าย) เป็น reportlab Paragraph ตัวเดียว
    รองรับ: #/##/### หัวข้อ, - หรือ * bullet, **ตัวหนา**  — ข้ามบรรทัด markdown
    table (ขึ้นต้นด้วย |) เพราะตาราง TFP เรนเดอร์แยกจากส่วนนี้อยู่แล้ว"""
    import re
    from reportlab.platypus import Paragraph

    raw = line.rstrip()
    if not raw.strip():
        return None
    if raw.strip().startswith("|") or set(raw.strip()) <= {"-", "|", " ", ":"}:
        return None  # ข้าม markdown table ที่หลงมา (กันเผื่อ AI ยังใส่มา)

    text = raw.strip()
    style_name = "ThaiBody"
    bullet = False

    if text.startswith("### "):
        text, style_name = text[4:], "ThaiH3"
    elif text.startswith("## "):
        text, style_name = text[3:], "ThaiH2"
    elif text.startswith("# "):
        text, style_name = text[2:], "ThaiH1"
    elif text.startswith("- ") or text.startswith("* "):
        text, bullet = text[2:], True

    # **bold** -> <b>bold</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    if bullet:
        text = "•  " + text

    return Paragraph(text, styles[style_name])


def markdown_to_flowables(md_text: str, styles) -> list:
    """แปลงข้อความสรุปผู้บริหาร (markdown อย่างง่ายจาก Gemini) เป็น list ของ
    reportlab flowables สำหรับใส่ใน PDF"""
    from reportlab.platypus import Spacer

    flowables = []
    for line in md_text.splitlines():
        para = _markdown_line_to_paragraph(line, styles)
        if para is not None:
            flowables.append(para)
            flowables.append(Spacer(1, 4))
    return flowables


def _build_pdf_styles():
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib import colors

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#0B2E52")
    gold = colors.HexColor("#B8860B")

    styles.add(ParagraphStyle("ThaiTitle", parent=styles["Title"], fontName="Sarabun-Bold",
                               fontSize=18, textColor=navy, spaceAfter=10, alignment=TA_LEFT))
    styles.add(ParagraphStyle("ThaiH1", parent=styles["Heading1"], fontName="Sarabun-Bold",
                               fontSize=14, textColor=navy, spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle("ThaiH2", parent=styles["Heading2"], fontName="Sarabun-Bold",
                               fontSize=12.5, textColor=navy, spaceBefore=8, spaceAfter=5))
    styles.add(ParagraphStyle("ThaiH3", parent=styles["Heading3"], fontName="Sarabun-Bold",
                               fontSize=11.5, textColor=gold, spaceBefore=6, spaceAfter=4))
    styles.add(ParagraphStyle("ThaiBody", parent=styles["Normal"], fontName="Sarabun",
                               fontSize=10.5, leading=15))
    styles.add(ParagraphStyle("ThaiCaption", parent=styles["Normal"], fontName="Sarabun",
                               fontSize=8, textColor=colors.grey, leading=11))
    return styles


def build_pdf_table_flowable(table_df: pd.DataFrame, adj_r2_lr: float, adj_r2_sr: float):
    """แปลง DataFrame จาก build_target_style_table() เป็น reportlab Table
    สไตล์กรมน้ำเงิน-ทอง (ใกล้เคียงตารางต้นฉบับ) พร้อมดาวนัยสำคัญและสัญลักษณ์ △/△²
    ต่อท้ายในช่องเดียวกับค่าสัมประสิทธิ์ระยะสั้น"""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    cell_style = ParagraphStyle("cell", fontName="Sarabun", fontSize=8.5, leading=11,
                                 textColor=colors.white)
    header_style = ParagraphStyle("cellhdr", fontName="Sarabun-Bold", fontSize=8.5,
                                   leading=11, textColor=colors.HexColor("#F5B800"),
                                   alignment=1)
    body_dark_style = ParagraphStyle("cellbody", fontName="Sarabun", fontSize=8.5,
                                      leading=11, textColor=colors.HexColor("#0B2E52"))

    header = [
        Paragraph("ตัวแปร", header_style),
        Paragraph("ค่าสัมประสิทธิ์<br/>สมการระยะยาว", header_style),
        Paragraph("ค่าสัมประสิทธิ์<br/>สมการระยะสั้น", header_style),
    ]
    data = [header]
    for _, row in table_df.iterrows():
        sr_text = row["ระยะสั้น"]
        if row["นัยสำคัญ"]:
            sr_text += f" {row['นัยสำคัญ']}"
        if row["หมายเหตุ"]:
            sr_text += f" {row['หมายเหตุ']}"
        data.append([
            Paragraph(row["ตัวแปร"], body_dark_style),
            Paragraph(row["ระยะยาว"], body_dark_style),
            Paragraph(sr_text, body_dark_style),
        ])

    tbl = Table(data, colWidths=[240, 130, 130], repeatRows=1)
    navy = colors.HexColor("#0B2E52")
    light_bg = colors.HexColor("#EAF1F8")
    white_bg = colors.white

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#F5B800")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8C4D4")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(data)):
        bg = light_bg if i % 2 == 1 else white_bg
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    # แถวสุดท้าย (Adj. R^2) ทำตัวหนา + เส้นบนหนา
    style_cmds.append(("FONTNAME", (0, -1), (-1, -1), "Sarabun-Bold"))
    style_cmds.append(("LINEABOVE", (0, -1), (-1, -1), 1.2, navy))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def build_pdf_report(
    lr_res, sr_res, model_df: pd.DataFrame, dep_ln: str, summary_text: str,
    report_title: str = "สรุปผู้บริหาร: ผลิตภาพการผลิตรวม (TFP) ของประเทศไทย",
) -> bytes:
    """สร้างรายงาน PDF ฉบับเต็ม (ตาราง TFP สไตล์ต้นฉบับ + บทสรุปผู้บริหารจาก AI)
    คืนค่าเป็น bytes พร้อมใช้กับ st.download_button(..., mime='application/pdf')
    ต้องมีฟอนต์ Sarabun ในโฟลเดอร์ fonts/ ก่อน (ดู register_thai_fonts)"""
    import io
    from datetime import datetime
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import cm

    register_thai_fonts()
    styles = _build_pdf_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        title=report_title,
    )

    story = [
        Paragraph(report_title, styles["ThaiTitle"]),
        Paragraph(f"จัดทำเมื่อ {datetime.now().strftime('%d/%m/%Y')}", styles["ThaiCaption"]),
        Spacer(1, 10),
        Paragraph("ตารางผลการทดสอบผลกระทบความสัมพันธ์ตัวแปร ววน. และผลิตภาพ (ECM)",
                   styles["ThaiH2"]),
        Spacer(1, 6),
    ]

    table_df = build_target_style_table(lr_res, sr_res)
    story.append(build_pdf_table_flowable(
        table_df, summary_adj_r2(lr_res), summary_adj_r2(sr_res)))
    story.append(Paragraph(
        "หมายเหตุ: ***, **, * หมายถึง นัยสำคัญที่ระดับความเชื่อมั่น 99%, 95%, 90% ตามลำดับ | "
        "&quot;-&quot; หมายถึงตัวแปรที่ไม่ได้อยู่ในสมการรุ่นนี้ | "
        "△ และ △² หมายถึงผลต่างลำดับที่ 1 และ 2 ตามลำดับ",
        styles["ThaiCaption"]))
    story.append(Spacer(1, 16))

    story.append(Paragraph("บทสรุปผู้บริหาร (สร้างโดย AI)", styles["ThaiH1"]))
    story.extend(markdown_to_flowables(summary_text, styles))

    doc.build(story)
    return buf.getvalue()


def run_full_pipeline(excel_path: str, sheet_name: str = SHEET_NAME):
    """รันทั้งไปป์ไลน์ (โหลดข้อมูล -> สร้าง log vars -> long-run -> short-run)
    คืนค่า (model_df, dep_ln, lr_res, sr_res) ให้ app.py เรียกใช้ได้ในฟังก์ชันเดียว"""
    raw = load_data(excel_path, sheet_name)
    model_df = build_model_frame(raw)
    dep_ln = "ln_" + DEP_VAR
    lr_res, lr_resid = run_long_run(model_df, dep_ln, LONG_RUN_VARS)
    sr_res = run_short_run(model_df, dep_ln, SHORT_RUN_SPEC, lr_resid)
    return model_df, dep_ln, lr_res, sr_res


# ------------------------------------------------------------------------------
# 6) MAIN (รันแบบ command line เฉย ๆ — ไม่มีส่วน AI แล้ว ไปเรียกผ่าน app.py แทน)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    raw = load_data(EXCEL_PATH, SHEET_NAME)
    model_df = build_model_frame(raw)
    print(f"ช่วงปีทั้งหมดที่มีในไฟล์ (ก่อนตัด NaN): {model_df.index.min()}-{model_df.index.max()}"
          f"  (n={len(model_df)}) -- ตอนนี้แต่ละสมการจะกำหนด sample ของตัวเองแยกกัน "
          f"(ดู 'Sample ที่ใช้จริง' ที่ print ต่อจาก STEP 1 / STEP 2 ด้านล่าง)")

    dep_ln = "ln_" + DEP_VAR

    print("\n=== ผลทดสอบ Unit Root (ADF) ของตัวแปรหลัก ===")
    all_vars = [dep_ln] + LONG_RUN_VARS + [c for c, _, _ in SHORT_RUN_SPEC]
    seen = set()
    for col in all_vars:
        if col not in seen and col in model_df.columns:
            print(adf_report(model_df[col], col))
            seen.add(col)

    lr_res, lr_resid = run_long_run(model_df, dep_ln, LONG_RUN_VARS)
    sr_res = run_short_run(model_df, dep_ln, SHORT_RUN_SPEC, lr_resid)