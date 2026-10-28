"""เกณฑ์ A ของหน้าเว็บ: 53 สถานะ (52 + v05b_backtest_run ตั้งแต่ 4c8aa71)ของโค้ดหน้าที่ย้ายต้องตรงกับผลเก็บหน้าจอของต้นฉบับบน runtime เดียวกันทุก element"""
import ui_parity


def test_pages_match_reference_screens():
    results, meta = ui_parity.run_all()
    bad = {s: d for s, d in results.items() if d}
    assert len(results) == 53, len(results)
    assert not bad, "\n".join(f"{s}: {d}" for s, d in bad.items())
