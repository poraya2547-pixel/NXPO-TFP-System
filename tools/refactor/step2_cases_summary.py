"""สรุปว่ากรณีใน backend/tests/test_parity_cases.py เดินผ่านทางไหนจริง (ok / error / ไม่มีสมการระยะสั้น)
ใช้เป็นหลักฐานว่า test ไม่ได้ผ่านเพราะทุกกรณีเหมือนกันหมดหรือว่างเปล่า — ไม่เขียนไฟล์ใน workspace
แสดงผลของฝั่งต้นฉบับ (ฝั่งใหม่ต้องตรงกันตาม test)

    PYTHONHASHSEED=0 /opt/anaconda3/envs/idntwww/bin/python -B -P -W ignore tools/refactor/step2_cases_summary.py
"""
import contextlib
import io
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "backend" / "tests")]
import test_parity_cases as t  # noqa: E402

warnings.simplefilter("ignore")
quiet = contextlib.redirect_stdout(io.StringIO())  # TFP.py พิมพ์ผล regression ออกจอ ไม่ต้องเก็บ
with quiet:
    orig, df_raw = t.load_original(), t.load_df_raw()


def kind(o):
    return o[0] if o[0] == "ok" else f"error {o[1]}: {o[2][:70]}"


print("== ชุดตัวแปร")
for name, lr, sr in t.VAR_SETS:
    with contextlib.redirect_stdout(io.StringIO()):
        out = t.pipeline(orig, df_raw.copy(), list(lr), list(sr))
    if "error" in out:
        print(f"{name}: error {out['error'][0]}: {out['error'][1][:70]}")
    elif out["sr"] is None:
        print(f"{name}: สมการระยะสั้นคืน None (หน้าเดิมแสดง error)")
    else:
        infl = out["influence"]
        infl_txt = kind(infl) if infl[0] != "ok" else (
            "ok" if infl[1]["items"][0] is not None else f"ok ข้อความ: {infl[1]['items'][1][:60]}")
        print(f"{name}: ตาราง {kind(out['combined_table'])} · diagnostics {kind(out['diag_display'])} · "
              f"influence {infl_txt} · scenario {len(out['scenario']['items'])} ตัวแปร")

print("\n== forecast/backtest edge cases")
series = t.tfp.build_model_frame(df_raw)[t.tfp.DEP_VAR].dropna().sort_index()
for name, fn, args, kwargs in t.edge_cases(series):
    with contextlib.redirect_stdout(io.StringIO()):
        o = t.outcome(orig["F"][fn], *args, **kwargs)
    detail = ""
    if o[0] == "ok" and isinstance(o[1], dict) and o[1].get("__type__") == "tuple":
        items = o[1]["items"]
        detail = " · " + ("ข้อความ: " + str(items[-1])[:60] if items[0] is None else f"{len(items)} ค่า")
    print(f"{name}: {kind(o)}{detail}")

print("\n== loader")
for name, tabs, kwargs, fail_first in t.loader_cases():
    client, clock = t.RecordingClient(tabs, fail_first), t.FakeTime()
    orig["L"]["_get_client"] = lambda: client
    orig["L"]["time"] = clock
    with contextlib.redirect_stdout(io.StringIO()):
        o = t.outcome(orig["L"]["load_data_gsheet"], **kwargs)
    print(f"{name}: {kind(o)} · key {sorted(set(client.keys))} · รอ {clock.sleeps}")
