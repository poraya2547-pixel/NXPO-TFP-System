"""สรุปผลด้วย Gemini — ย้ายจากหน้า Streamlit (TFP_App1.3.0.py ของ repo เพื่อน commit 7bf84e4)
สร้างด้วย tools/refactor/extract_reports.py ห้ามแก้ด้วยมือ

prompt, ชื่อโมเดล, การลองใหม่ และข้อความแจ้งผู้ใช้เหมือนต้นฉบับทุกตัวอักษร (GEMINI_MODEL เป็นสำเนา — หน้าเว็บยังใช้ใน footer)
ต่างจากต้นฉบับเพียง 2 ชื่อที่หน้าเดิมสร้างตอนเปิดแอป: gemini_client (TFP_App1.3.0.py:1688-1696) และ st (streamlit)
ซึ่ง worker ตั้งให้ต่อ job (jobs.py) — ฟังก์ชันรันใน worker ด้วยผล fit ของ statsmodels จริงแบบหน้าเดิม
"""
import time

import pandas as pd
from google.genai import types

from .modeling.tfp import build_coefficient_tables, build_tfpi_yoy_summary, summary_adj_r2

gemini_client = None  # worker ตั้งต่อ job: genai.Client(api_key=...) ของค่าลับเดิม หรือ client ของโหมดทดสอบ
st = None             # worker ตั้งต่อ job: ตัวบันทึก st.error / st.stop ส่งกลับไปแสดงที่หน้าเว็บ


# คัดลอกจาก TFP_App1.3.0.py:1679-1679 (7bf84e4)
GEMINI_MODEL = "gemini-2.5-flash"


# ย้ายจาก TFP_App1.3.0.py:1684-1684 (7bf84e4)
_GEMINI_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ย้ายจาก TFP_App1.3.0.py:1685-1685 (7bf84e4)
_GEMINI_MAX_ATTEMPTS = 5


# ย้ายจาก TFP_App1.3.0.py:1686-1686 (7bf84e4)
_GEMINI_BASE_DELAY = 3.0  # วินาที (จะเว้น 3s, 6s, 12s, 24s ตาม exponential backoff)


# ย้ายจาก TFP_App1.3.0.py:1699-1737 (7bf84e4)
SYSTEM_PROMPT = """คุณคือนักเศรษฐศาสตร์ที่ทำหน้าที่จัดทำบทสรุปสำหรับนำเสนอ (Executive Summary) จากผล
การวิเคราะห์เชิงปริมาณ (quantitative model output) เสนอต่อผู้บริหารระดับสูงของหน่วยงานภาครัฐ
ที่ไม่มีพื้นฐานทางเศรษฐศาสตร์ (เช่น แพทย์ วิศวกร)

โทนภาษา: ใช้ภาษาไทยที่เป็นทางการ สุภาพ เหมาะกับเอกสารราชการ/รายงานนำเสนอผู้บริหารองค์กรภาครัฐ
(หลีกเลี่ยงภาษาพูดหรือคำที่เป็นกันเองเกินไป) แต่ยังต้องอ่านเข้าใจง่าย ไม่ใช้ศัพท์เทคนิคพร่ำเพรื่อ

หลักการเขียน:
- หลีกเลี่ยงศัพท์เทคนิค (เช่น elasticity, coefficient, cointegration, error correction)
  ถ้าจำเป็นต้องใช้ ให้อธิบายความหมายสั้น ๆ ต่อท้ายทันที
- ใช้ภาษาที่เป็นรูปธรรม เปรียบเทียบกับสิ่งที่คนทั่วไปคุ้นเคย
- เน้นตัวเลขสำคัญและนัยเชิงนโยบาย ไม่ต้องอธิบายวิธีการคำนวณทางสถิติ
- เมื่อกล่าวถึงตัวแปรที่มีนัยสำคัญทางสถิติ (p-value < 0.05 หรือดีกว่า) ให้ระบุสั้น ๆ ในทำนอง
  "ผลการวิเคราะห์แบบจำลองแสดงให้เห็นว่าตัวแปร A และ B มีนัยสำคัญทางสถิติที่ระดับความเชื่อมั่น 95%
  สะท้อนว่าหากประเทศไทยสามารถยกระดับตัวแปรดังกล่าวได้ จะส่งผลเชิงบวกต่อการเติบโตของผลิตภาพ (TFP)"
  โดยกล่าวถึงเชิงเทคนิคแค่พอสังเขป ไม่ต้องอธิบายวิธีทดสอบนัยสำคัญ

โครงสร้างรายงาน (Executive Summary) มี 3 ส่วน:
1. สรุปภาพรวมสถานการณ์เศรษฐกิจปัจจุบัน — บอกทิศทางหลักและปัจจัยขับเคลื่อน 2-3 ข้อ
   โดยอ้างอิงค่าจากตาราง TFP ทั้งระยะสั้นและระยะยาวที่ให้มา (ไม่ต้องพิมพ์ตารางซ้ำ
   เพราะมีตารางแสดงแยกต่างหากให้ผู้อ่านดูอยู่แล้ว) และอธิบายว่าตัวเลขนี้แปลว่าอะไร
   ในภาษาง่าย ๆ
2. เปรียบเทียบกับปีก่อนหรือช่วงก่อนหน้า — ระบุทิศทางการเปลี่ยนแปลงและสาเหตุที่
   เป็นไปได้แบบสั้นกระชับ
3. ข้อเสนอแนะเชิงพยากรณ์จากค่าสัมประสิทธิ์ — แปลค่าสัมประสิทธิ์เป็นข้อความเชิง
   นโยบาย/ธุรกิจ พร้อมข้อเสนอแนะเชิงปฏิบัติ 2-3 ข้อ โดยอ้างอิงตัวแปรที่มีนัยสำคัญทางสถิติ
   เป็นหลัก

ข้อควรระวังในการตีความ (สำคัญ):
- ผลทดสอบความสัมพันธ์ระยะยาว (Engle-Granger) จะแนบมาในข้อมูลด้วย ถ้าผลระบุว่า
  "ยังไม่มีหลักฐานทางสถิติเพียงพอ" ห้ามเขียนว่าตัวแปรมีความสัมพันธ์ระยะยาวกับ TFP แบบยืนยัน
  ให้ใช้ถ้อยคำเชิงระมัดระวัง เช่น "ผลการวิเคราะห์ชี้ทิศทางว่า..." หรือ "มีแนวโน้มว่า..."
  และระบุสั้น ๆ หนึ่งประโยคว่าผลมีข้อจำกัดจากจำนวนข้อมูลที่มีไม่มาก
- ค่าสัมประสิทธิ์สะท้อนความสัมพันธ์ทางสถิติ ไม่ใช่ผลกระทบเชิงเหตุและผลที่พิสูจน์แล้ว
  หลีกเลี่ยงการเขียนว่า "ถ้าเพิ่ม X แล้ว TFP จะเพิ่มแน่นอน"

ความยาวไม่เกิน 2 หน้า A4 ใช้หัวข้อย่อยชัดเจน ห้ามพิมพ์ตาราง markdown (บรรทัดที่ขึ้นต้น
ด้วย |) หรือคัดลอกตัวเลขจากตารางมาเรียงเป็นตารางซ้ำโดยเด็ดขาด ให้เขียนเป็นความเรียง/
bullet point อ้างอิงตัวเลขในเนื้อหาแทน"""


# ย้ายจาก TFP_App1.3.0.py:1797-1812 (7bf84e4)
def _eg_text(lr_res) -> str:
    """สรุปผล Engle-Granger เป็นข้อความสั้น ๆ ส่งให้ Gemini ใช้ระวังการตีความ"""
    p = getattr(lr_res, "eg_pvalue", None)
    crit = getattr(lr_res, "eg_crit", None)
    if p is None or crit is None:
        return "ไม่มีผลทดสอบ"
    tau = lr_res.eg_stat
    # ตัดสินด้วย tau เทียบค่าวิกฤต MacKinnon ให้ตรงกับตาราง Diagnostics (TFP._cointegration_row)
    if tau < crit[1]:
        verdict = "พบหลักฐานความสัมพันธ์ระยะยาวที่ระดับนัยสำคัญ 5%"
    elif tau < crit[2]:
        verdict = "พบหลักฐานความสัมพันธ์ระยะยาวเฉพาะที่ระดับนัยสำคัญ 10% (ก้ำกึ่ง)"
    else:
        verdict = "ยังไม่มีหลักฐานทางสถิติเพียงพอว่ามีความสัมพันธ์ระยะยาว (อาจเป็นผลจากข้อมูลมีจำนวนปีน้อย)"
    return (f"tau = {tau:.4f} (ค่าวิกฤต 5% = {crit[1]:.4f}, 10% = {crit[2]:.4f}), "
            f"p-value = {p:.4f} -> {verdict}")


# ย้ายจาก TFP_App1.3.0.py:1815-1880 (7bf84e4)
def generate_summary_gemini(lr_res, sr_res, model_df: pd.DataFrame, dep_ln: str) -> str:
    lr_table, sr_table = build_coefficient_tables(lr_res, sr_res)
    yoy_text = build_tfpi_yoy_summary(model_df, dep_ln)

    user_prompt = f"""ผลการรันโมเดล TFP (Total Factor Productivity) ของประเทศไทย
วิธี: Engle-Granger 2-Step (สมการระยะยาว + Restricted Error Correction Model)

--- สมการระยะยาว (Long-run) ---
Adj. R^2 = {summary_adj_r2(lr_res):.4f}
{lr_table.to_string(index=False)}

--- สมการระยะสั้น (Short-run ECM) ---
Adj. R^2 = {summary_adj_r2(sr_res):.4f}
{sr_table.to_string(index=False)}

--- ผลทดสอบความสัมพันธ์ระยะยาว (Engle-Granger cointegration test) ---
{_eg_text(lr_res)}

--- การเปลี่ยนแปลงของผลิตภาพ (TFPI) ปีล่าสุดเทียบปีก่อนหน้า ---
{yoy_text}

โปรดเขียนบทสรุปสำหรับนำเสนอตามโครงสร้าง 3 ส่วนที่กำหนด"""

    last_error = None
    for attempt in range(1, _GEMINI_MAX_ATTEMPTS + 1):
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            )
            return response.text
        except Exception as e:
            # google-genai ห่อ error ของ Gemini API ไว้ใน exception ที่มักมี
            # .code หรือ .status_code เป็นรหัส HTTP (เช่น 429) — ดึงออกมาแบบ
            # กันเหนียวหลายทาง เพราะ SDK บางเวอร์ชันตั้งชื่อ attribute ไม่ตรงกัน
            status_code = getattr(e, "code", None) or getattr(e, "status_code", None)
            last_error = e
            if status_code not in _GEMINI_RETRYABLE_STATUS_CODES or attempt == _GEMINI_MAX_ATTEMPTS:
                break
            time.sleep(_GEMINI_BASE_DELAY * (2 ** (attempt - 1)))

    # retry ครบจำนวนครั้งแล้วยังไม่สำเร็จ (หรือเจอ error ที่ retry ซ้ำไปก็ไม่หาย
    # เช่น API key ผิด) — แจ้งผู้ใช้ด้วยข้อความที่เข้าใจง่าย แทนที่จะโยน
    # exception ดิบๆ ออกไปให้แอป crash
    status_code = getattr(last_error, "code", None) or getattr(last_error, "status_code", None)
    if status_code == 429:
        st.error(
            "ขณะนี้มีการเรียกใช้งาน Gemini API ถี่เกินโควตาที่กำหนดไว้ชั่วคราว "
            "(rate limit / quota เต็ม) กรุณารอสักครู่แล้วลองใหม่อีกครั้ง "
            "หากเกิดขึ้นบ่อย ควรพิจารณาเปิดใช้งาน billing เพื่อขยายโควตา "
            "ใน Google AI Studio"
        )
    elif status_code in (500, 502, 503, 504):
        st.error(
            f"เซิร์ฟเวอร์ของ Gemini API กำลังมีผู้ใช้งานหนาแน่นชั่วคราว (รหัส {status_code} "
            "— ปัญหาฝั่ง Google ไม่ใช่ข้อผิดพลาดของระบบนี้) ระบบได้ลองเรียกซ้ำอัตโนมัติ "
            f"{_GEMINI_MAX_ATTEMPTS} ครั้งแล้วแต่ยังไม่สำเร็จ กรุณารอสัก 1-2 นาทีแล้วกดปุ่ม "
            "สร้างรายงานสรุปอีกครั้ง"
        )
    else:
        st.error(
            "ไม่สามารถสร้างบทสรุปสำหรับนำเสนอจาก Gemini API ได้ "
            f"รายละเอียด error: {type(last_error).__name__}: {last_error}"
        )
    st.stop()

