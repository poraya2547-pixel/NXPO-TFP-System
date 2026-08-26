"""
================================================================================
data_loader.py — ดึงข้อมูลจาก Google Sheets แทนการอัปโหลดไฟล์ Excel
================================================================================
ทำหน้าที่แทนที่ load_data() ใน TFP.py: ทำ preprocessing แบบเดียวกันทุก
ขั้นตอน (rename คอลัมน์, ตั้ง index เป็นปี, หารคอลัมน์ % ด้วย 100, ดึง
RDH_GDP จากแท็บ Researcher) เพียงแต่อ่านจาก Google Sheets แทนไฟล์ .xlsx

ข้อกำหนดโครงสร้าง Google Sheet (ต้องเหมือนไฟล์ Excel เดิมเป๊ะ):
    - แท็บ "Data": แถวที่ 1 = หัวคอลัมน์, แถวที่ 2-3 = หน่วย/คำอธิบาย (ถูกข้าม),
      แถวที่ 4 เป็นต้นไป = ข้อมูลรายปี (คอลัมน์แรกสุด = ปี)
    - แท็บ "Researcher": คอลัมน์ A = ชื่อประเทศ (ต้องมีแถวที่มีคำว่า "Thailand"),
      ข้อมูลตัวเลขเริ่มที่คอลัมน์ C เป็นต้นไป ตรงกับปี 1996-2022 เรียงลำดับ

ถ้าโครงสร้างแท็บไม่ตรงตามนี้ ให้แก้ตำแหน่ง DATA_TAB / RESEARCHER_TAB หรือ
ปรับ index การตัดแถว/คอลัมน์ในฟังก์ชันด้านล่างให้ตรงกับ Sheet จริงของคุณ
================================================================================
"""

import time

import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st

from TFP import RAW_TO_MODEL, PERCENT_VARS, RDH_SOURCE

# ------------------------------------------------------------------------------
# CONFIG — แก้ตรงนี้ถ้า Sheet ID หรือชื่อแท็บเปลี่ยน
# ------------------------------------------------------------------------------
SHEET_ID = "1K3POpW0qUCRqkx4nDxyXblHsLlbmmQCnDqFY6Blv2Ug"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

DATA_TAB = "Data"              # ชื่อแท็บข้อมูลหลัก (เทียบเท่าชีต "Data" เดิม)
RESEARCHER_TAB = "Researcher"  # ชื่อแท็บ RDH_GDP จาก OECD.Stat (เทียบเท่าชีต "Researcher" เดิม)

# รหัสสถานะ HTTP ที่ถือว่าเป็นปัญหาชั่วคราวฝั่ง Google เอง (server error/
# service unavailable) — คุ้มค่าที่จะลองใหม่อัตโนมัติ ต่างจาก 4xx อย่าง 403/404
# ที่เป็นปัญหาสิทธิ์/การตั้งค่าซึ่งลองกี่ครั้งก็ไม่หาย
_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


def _call_with_retry(func, *args, max_attempts: int = 3, base_delay: float = 1.5, **kwargs):
    """เรียก func(*args, **kwargs) พร้อม retry อัตโนมัติสูงสุด max_attempts ครั้ง
    เฉพาะตอนเจอ gspread.exceptions.APIError ที่เป็นปัญหาชั่วคราวฝั่ง Google
    (เช่น 503 Service Unavailable) โดยเว้นระยะห่างแบบ exponential backoff
    (1.5s, 3s, 6s, ...) ก่อนลองใหม่แต่ละครั้ง — ช่วยให้แอปสาธารณะทนต่อ Google
    API ที่หลุด/ล่มชั่วคราวได้เองโดยผู้ใช้ไม่ต้องกดปุ่มดึงข้อมูลซ้ำเอง

    ถ้าเจอ error ที่ไม่ retryable (เช่น 403 สิทธิ์ไม่พอ) หรือ retry ครบจำนวน
    ครั้งแล้วยังไม่สำเร็จ จะโยน exception เดิมออกไปตามปกติ"""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            status_code = None
            try:
                status_code = e.response.json().get("error", {}).get("code")
            except Exception:
                pass
            last_error = e
            if status_code not in _RETRYABLE_STATUS_CODES or attempt == max_attempts:
                raise
            time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_error


def _get_client() -> gspread.Client:
    """สร้าง gspread client จากคีย์ service account

    อ่านจาก st.secrets["gcp_service_account"] ก่อนเป็นหลัก (ใช้ตอนรันผ่าน
    Streamlit ทั้งตอนรันบนเครื่องและตอน deploy ขึ้นเว็บสาธารณะ — ปลอดภัยกว่า
    เพราะไม่ต้องมีไฟล์ credentials.json วางอยู่ในโปรเจกต์/repo เลย ตัวคีย์จะ
    ถูกเก็บใน .streamlit/secrets.toml บนเครื่อง หรือในช่อง Secrets ของ
    Streamlit Cloud เท่านั้น)

    ถ้าไม่มี st.secrets ตั้งค่านี้ไว้ (เช่นตอนรันไฟล์นี้ตรงๆ ด้วยคำสั่ง
    `python data_loader.py` นอก Streamlit เพื่อทดสอบ) จะ fallback ไปอ่านจาก
    ไฟล์ credentials.json ในโฟลเดอร์เดียวกันแทน เพื่อให้ยังทดสอบนอก Streamlit
    ได้ตามปกติ (ไฟล์ credentials.json นี้ไม่ควร push ขึ้น git — ใส่ไว้ใน
    .gitignore เหมือนเดิม)

    ถ้าทั้งสองทางล้มเหลว จะโยน error ที่รวมเหตุผลของทั้งสองทางไว้ในข้อความ
    เดียว ช่วยให้รู้ทันทีว่าปัญหาอยู่ที่ secrets.toml หรือไฟล์ credentials.json"""
    secrets_error = None
    try:
        info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        secrets_error = e

    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as file_error:
        raise RuntimeError(
            "เชื่อมต่อ Google Sheets ไม่สำเร็จ ลองมาแล้ว 2 ทาง:\n"
            f"1) จาก st.secrets['gcp_service_account'] → {type(secrets_error).__name__}: {secrets_error}\n"
            f"2) จากไฟล์ credentials.json → {type(file_error).__name__}: {file_error}\n"
            "ตรวจสอบว่า .streamlit/secrets.toml มีตาราง [gcp_service_account] "
            "ที่ครบทุกฟิลด์และ private_key ไม่ถูกตัดตอน"
        ) from file_error


def _load_researcher_rdh(client: gspread.Client, country: str = "Thailand") -> pd.Series:
    """เทียบเท่า load_researcher_rdh() ใน TFP.py แต่ดึงจากแท็บ Google Sheet
    แทนชีต Excel"""
    ws = _call_with_retry(lambda: client.open_by_key(SHEET_ID).worksheet(RESEARCHER_TAB))
    values = _call_with_retry(ws.get_all_values)
    try:
        row = next(r for r in values if r and country in r[0])
    except StopIteration:
        raise ValueError(
            f'ไม่พบแถวที่มีคำว่า "{country}" ในแท็บ "{RESEARCHER_TAB}" '
            f"— ตรวจสอบว่าคอลัมน์ A มีชื่อประเทศอยู่จริง"
        )
    years = list(range(1996, 2023))
    vals = pd.to_numeric(pd.Series(row[2:2 + len(years)], index=years), errors="coerce")
    return vals.rename("RDH_GDP")


def load_data_gsheet(rdh_source: str = RDH_SOURCE) -> pd.DataFrame:
    """เทียบเท่า load_data() ใน TFP.py ทุกขั้นตอน (rename, ตั้งปีเป็น index,
    หาร % ด้วย 100, ดึง RDH_GDP จากแท็บ Researcher) แต่อ่านจาก Google Sheets
    คืนค่าเป็น DataFrame รูปแบบเดียวกับที่ TFP.build_model_frame() คาดหวัง"""
    client = _get_client()
    ws = _call_with_retry(lambda: client.open_by_key(SHEET_ID).worksheet(DATA_TAB))
    values = _call_with_retry(ws.get_all_values)

    if len(values) < 4:
        raise ValueError(
            f'แท็บ "{DATA_TAB}" มีข้อมูลไม่ครบ (ต้องมีอย่างน้อย 4 แถว: '
            f"หัวคอลัมน์ + หน่วย/คำอธิบาย 2 แถว + ข้อมูลอย่างน้อย 1 แถว)"
        )

    header = values[0]
    data_rows = values[3:]  # ข้ามแถว header(0) และหน่วย/คำอธิบาย (1,2) เหมือน skiprows=[1,2]

    raw = pd.DataFrame(data_rows, columns=header)
    raw = raw.loc[:, ~raw.columns.duplicated()]  # กันเหนียวกรณีมีคอลัมน์ชื่อซ้ำ/ว่าง
    raw = raw.rename(columns={raw.columns[0]: "year"})
    raw = raw.rename(columns=RAW_TO_MODEL)

    raw = raw[raw["year"].astype(str).str.strip() != ""]  # ตัดแถวว่างท้ายตาราง
    raw["year"] = raw["year"].astype(int)
    raw = raw.set_index("year")

    keep = [c for c in RAW_TO_MODEL.values() if c in raw.columns]
    df = raw[keep].copy()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in PERCENT_VARS:
        if col in df.columns:
            df[col] = df[col] / 100.0

    if rdh_source == "researcher":
        rdh = _load_researcher_rdh(client)
        df["RDH_GDP"] = rdh.reindex(df.index)
    elif rdh_source != "data":
        raise ValueError('rdh_source ต้องเป็น "researcher" หรือ "data"')

    return df


# ทดสอบรันไฟล์นี้ตรงๆ (จะไม่รันตอนถูก import จากไฟล์อื่นอย่าง app.py)
if __name__ == "__main__":
    df = load_data_gsheet()
    print(df)