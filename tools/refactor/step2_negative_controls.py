"""Step 2 negative controls: ยืนยันว่า test ตรวจจับความต่างได้จริง (ไม่ผ่านแบบว่างเปล่า)

- กราฟ: charts.py ก่อนแก้ (private/verification/step2-regenerate/charts.py, legend_html เป็น tuple) ต้องตก
- โครงสร้างโค้ด: แก้สำเนาของ backend/app ในโฟลเดอร์ชั่วคราวทีละจุด แล้วรัน test เดิม ต้องตกทุกจุด
ไม่แก้ไฟล์ใน workspace (แก้เฉพาะสำเนาชั่วคราว)

    PYTHONHASHSEED=0 /opt/anaconda3/envs/idntwww/bin/python -B -P -W ignore tools/refactor/step2_negative_controls.py
"""
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "backend" / "tests")]
import parity  # noqa: E402  (ตั้ง sys.path ของ backend/tools)
import test_charts  # noqa: E402
import test_moved_source  # noqa: E402

results = []


def expect_fail(label, fn):
    try:
        fn()
    except AssertionError as e:
        results.append(f"ตกตามคาด  {label}: {str(e).splitlines()[0][:100] if str(e) else 'AssertionError'}")
        return
    results.append(f"ไม่ตก (ผิดคาด) {label}")


def expect_pass(label, fn):
    fn()
    results.append(f"ผ่าน      {label}")


# 1) กราฟ: charts.py ก่อนแก้ (legend_html เป็น tuple) ต้องตก
from app import data_loader  # noqa: E402
from app.modeling import core, tfp  # noqa: E402

tabs = parity.replay.load_tabs()
real = data_loader._get_client
data_loader._get_client = lambda: parity.replay._FakeClient(tabs)
try:
    model_df = tfp.build_model_frame(data_loader.load_data_gsheet())
finally:
    data_loader._get_client = real
s = model_df[tfp.DEP_VAR].dropna().sort_index()
mini = {"outputs": {"tfp_series": s, "model_df": model_df,
                    **{f"forecast.h{h}": core._drift_forecast_interval(s, h) for h in parity.oracle.HORIZONS}}}
expect_pass("กราฟพยากรณ์ด้วย charts.py ปัจจุบัน", lambda: test_charts.test_forecast_charts_match_original(mini))
spec = importlib.util.spec_from_file_location("charts_prefix", REPO / "private/verification/step2-regenerate/charts.py")
prefix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prefix)
test_charts.charts = prefix
expect_fail("กราฟพยากรณ์ด้วย charts.py ก่อนแก้ (legend_html เป็น tuple)",
            lambda: test_charts.test_forecast_charts_match_original(mini))

# 2) โครงสร้างโค้ด: แก้สำเนาทีละจุด ต้องตก
MUTATIONS = [
    ("core.py ค่าใน _run_rolling_backtest", "modeling/core.py", "test_core_is_original_code",
     "crisis_years", "crisis_yearz"),
    ("core.py ใส่ cache decorator กลับ", "modeling/core.py", "test_core_is_original_code",
     "def _auto_arima_forecast(", "@staticmethod\ndef _auto_arima_forecast("),
    ("charts.py สีขอบ legend", "charts.py", "test_charts_differ_only_in_returning_output",
     "border-radius:2px", "border-radius:3px"),
    ("data_loader.py scopes", "data_loader.py", "test_data_loader_differs_only_where_declared",
     '"https://www.googleapis.com/auth/drive"]', '"https://www.googleapis.com/auth/drive.readonly"]'),
    ("data_loader.py ไฟล์สำรอง", "data_loader.py", "test_data_loader_differs_only_where_declared",
     "config.credentials_file()", '"credentials.json"'),
    ("scenario.py 100 -> 100.0", "modeling/scenario.py", "test_scenario_formula_is_the_inline_code",
     "shock / 100)", "shock / 100.0)"),
]
for label, rel, test_name, old, new in MUTATIONS:
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "app"
        shutil.copytree(REPO / "backend" / "app", dst)
        text = (dst / rel).read_text(encoding="utf-8")
        assert text.count(old) >= 1, (label, old)
        (dst / rel).write_text(text.replace(old, new, 1), encoding="utf-8")
        test_moved_source.NEW = dst
        expect_fail(label, getattr(test_moved_source, test_name))
test_moved_source.NEW = REPO / "backend" / "app"
for name in ("test_core_is_original_code", "test_charts_differ_only_in_returning_output",
             "test_data_loader_differs_only_where_declared", "test_scenario_formula_is_the_inline_code"):
    expect_pass(f"{name} บนไฟล์จริง", getattr(test_moved_source, name))

print("\n".join(results))
bad = [r for r in results if "ผิดคาด" in r]
print(f"\nสรุป: {len(results) - len(bad)}/{len(results)} ตามคาด")
sys.exit(1 if bad else 0)
