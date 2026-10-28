"""Step 1: อ่าน Google Sheets จริงหนึ่งรอบด้วย loader เดิม (อ่านอย่างเดียว) แล้วเก็บ snapshot

ไม่แก้ data_loader.py: ดักเก็บเฉพาะค่าที่ gspread คืนจาก get_all_values() เป็นสำเนา
ผลเก็บใน private/baseline/ (ไม่ขึ้น git) พิมพ์เฉพาะสรุป ไม่พิมพ์คีย์หรือค่าในชีต

ต้องระบุชื่อ snapshot และห้ามซ้ำกับที่มีอยู่ ระบบตรวจก่อนต่อเครือข่าย จึงไม่ทับ snapshot เดิม
ชื่อ baseline คือชุดอ้างอิงที่เก็บแล้ว (sheets_raw.json) ใช้ซ้ำไม่ได้

    /opt/anaconda3/envs/idntwww/bin/python -B tools/baseline/fetch_snapshot.py <ชื่อใหม่>
"""
import datetime
import json
import os
import pickle
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "private" / "baseline"
sys.path.insert(0, str(HERE))
import safe_io  # noqa: E402


def targets(name: str) -> dict:
    safe_io.check_name(name)
    suffix = "" if name == "baseline" else f"_{name}"
    return {
        "snapshot": OUT / f"sheets_raw{suffix}.json",
        "df": OUT / f"raw_df_live{suffix}.pkl",
        "summary": OUT / f"snapshot_summary{suffix}.json",
    }


def ensure_new(name: str) -> dict:
    paths = targets(name)
    safe_io.ensure_absent(paths.values())
    return paths


def main(name: str):
    paths = ensure_new(name)  # ตรวจก่อนต่อเครือข่าย
    os.chdir(REPO)  # secrets.toml / credentials.json ของเดิมอ้างอิงจากโฟลเดอร์ที่รัน
    sys.path.insert(0, str(REPO))
    import gspread
    import fingerprint

    recorded = {}
    original = gspread.worksheet.Worksheet.get_all_values

    def recording(self, *args, **kwargs):
        values = original(self, *args, **kwargs)
        recorded[self.title] = [list(row) for row in values]
        return values

    gspread.worksheet.Worksheet.get_all_values = recording

    import data_loader

    t0 = time.perf_counter()
    df = data_loader.load_data_gsheet()
    elapsed = time.perf_counter() - t0
    fetched_at = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).isoformat(timespec="seconds")

    safe_io.write_new(paths["snapshot"], json.dumps({
        "fetched_at": fetched_at,
        "source": "data_loader.load_data_gsheet() ค่าเริ่มต้น (SHEET_ID ในโค้ดเดิม)",
        "gspread": gspread.__version__,
        "elapsed_s": round(elapsed, 3),
        "tabs": recorded,
    }, ensure_ascii=False, indent=1))
    safe_io.write_new(paths["df"], pickle.dumps(df))

    import replay
    df_replay = replay.load_df_from_snapshot(paths["snapshot"])

    import TFP
    df_xlsx = TFP.load_data(TFP.EXCEL_PATH, TFP.SHEET_NAME)

    summary = {
        "fetched_at": fetched_at,
        "elapsed_s": round(elapsed, 3),
        "tabs": {t: {"rows": len(v), "cols": max((len(r) for r in v), default=0)} for t, v in recorded.items()},
        "tabs_sha256": fingerprint.sha256(recorded),
        "df_shape": list(df.shape),
        "df_years": [int(df.index.min()), int(df.index.max())],
        "df_columns": [str(c) for c in df.columns],
        "df_dtypes": sorted({str(t) for t in df.dtypes}),
        "df_nan_counts": {str(c): int(df[c].isna().sum()) for c in df.columns},
        "df_sha256": fingerprint.sha256(df),
        "replay_identical": fingerprint.dumps(df) == fingerprint.dumps(df_replay),
        "excel_vs_sheets": compare_frames(df, df_xlsx),
    }
    safe_io.write_new(paths["summary"], json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def compare_frames(sheets, excel) -> dict:
    """เทียบข้อมูลจาก Sheets กับ Excel ทีละคอลัมน์ รายงานเฉพาะจำนวนช่องที่ต่าง ไม่พิมพ์ค่า"""
    import numpy as np

    years = sheets.index.intersection(excel.index)
    out = {
        "sheets_years": [int(sheets.index.min()), int(sheets.index.max())],
        "excel_years": [int(excel.index.min()), int(excel.index.max())],
        "only_in_sheets_cols": sorted(set(map(str, sheets.columns)) - set(map(str, excel.columns))),
        "only_in_excel_cols": sorted(set(map(str, excel.columns)) - set(map(str, sheets.columns))),
        "columns": {},
    }
    for col in [c for c in sheets.columns if c in excel.columns]:
        a = sheets.loc[years, col].to_numpy(dtype=float)
        b = excel.loc[years, col].to_numpy(dtype=float)
        nan_a, nan_b = np.isnan(a), np.isnan(b)
        both = ~nan_a & ~nan_b
        out["columns"][str(col)] = {
            "nan_mask_diff": int((nan_a != nan_b).sum()),
            "value_diff": int((a[both] != b[both]).sum()),
            "max_abs_diff": float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0,
        }
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("ต้องระบุชื่อ snapshot ใหม่หนึ่งชื่อ เช่น fetch_snapshot.py 2026-10-01")
    try:
        main(sys.argv[1])
    except (FileExistsError, ValueError) as e:
        sys.exit(str(e))
