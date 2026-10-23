"""negative controls ของตัวเทียบหน้าจอ (backend/tests/ui_parity.py): แก้ผลฝั่งใหม่ทีละจุดแล้วต้องตกทุกจุด
(ยืนยันว่า 52/52 ไม่ได้ผ่านเพราะตัวเทียบหลวม) — ไม่เขียนไฟล์ใน workspace

    PYTHONHASHSEED=0 /opt/anaconda3/envs/idntwww/bin/python -B -P -W ignore tools/refactor/step3_ui_negative_controls.py
"""
import copy
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "backend" / "tests")]
import ui_parity as u  # noqa: E402

STATE = "v07_scenario_FDI_GDP_shock5_0"
ADF_STATE = "r04_home"  # ตาราง ADF/diagnostics ของต้นฉบับ 7bf84e4


def find(node, pred):
    if pred(node):
        return node
    for c in node.get("children", []):
        r = find(c, pred)
        if r is not None:
            return r
    return None


def main():
    refs, _ = u.reference_states(u.parity.reference_set())
    states = u.drive(u.load_snapshot_df())
    tree, values, store = states[STATE]
    downloads = store._downloads_by_ref()
    base = u.compare_state(refs[STATE], tree, values, downloads)
    print(("ผ่าน      " if not base else "ไม่ผ่าน   ") + f"ผลจริงของ {STATE}")
    results = [not base]

    def mut(label, change, vals=None):
        t = copy.deepcopy(tree)
        change(t)
        d = u.compare_state(refs[STATE], t, values if vals is None else vals, downloads)
        results.append(bool(d))
        print(("ตกตามคาด  " if d else "ไม่ตก (ผิดคาด) ") + label + (f" — {d[0]}" if d else ""))

    def card(t):
        n = find(t["main"], lambda n: n.get("type") == "markdown" and "font-size:1.65rem" in n.get("body", ""))
        n["body"] = n["body"].replace("+3.73%", "+3.74%")

    def chart_value(t):
        c = find(t["main"], lambda n: n.get("type") == "vega_lite_chart")
        rows = next(iter(c["spec"]["datasets"].values()))
        k = [k for k, v in rows[-1].items() if isinstance(v, float)][0]
        rows[-1][k] = rows[-1][k] + 1e-12

    def download(t):
        n = find(t["main"], lambda n: n.get("type") == "download_button")
        downloads["<แก้แล้ว>"] = (downloads[n["ref"]][0] + b" ", *downloads[n["ref"]][1:])
        n["ref"] = "<แก้แล้ว>"

    mut("ตัวเลขในการ์ดผลกระทบ +3.73% → +3.74%", card)
    mut("ตัวเลือกช่อง horizon", lambda t: find(t["main"], lambda n: n.get("type") == "selectbox")["options"]
        .__setitem__(0, "x"))
    mut("ค่าในข้อมูลกราฟ +1e-12", chart_value)
    mut("ความสูงใน spec กราฟ", lambda t: find(t["main"], lambda n: n.get("type") == "vega_lite_chart")["spec"]
        .__setitem__("height", 341))
    mut("ป้ายปุ่มใน sidebar", lambda t: find(t["sidebar"], lambda n: n.get("type") == "button")
        .__setitem__("label", "x"))
    mut("น้ำหนักคอลัมน์", lambda t: find(t["main"], lambda n: n.get("type") == "column").__setitem__("weight", 0.5))
    mut("element ท้ายหน้าหาย", lambda t: t["main"]["children"].pop())
    mut("element เกิน", lambda t: t["main"]["children"].append(
        {"type": "markdown", "kind": "markdown", "body": "", "allow_html": False}))
    mut("เนื้อไฟล์ดาวน์โหลดต่าง 1 byte", download)
    mut("ค่า session page", lambda t: None, dict(values, page="home"))

    # ส่วนที่มีตั้งแต่ 7bf84e4: ตาราง ADF รายตัวแปร, ไฟล์ CSV ของตาราง และชื่อหมวดใน diagnostics (หน้า home คณะวิจัย)
    tree2, values2, store2 = states[ADF_STATE]
    downloads2 = store2._downloads_by_ref()
    base2 = u.compare_state(refs[ADF_STATE], tree2, values2, downloads2)
    print(("ผ่าน      " if not base2 else "ไม่ผ่าน   ") + f"ผลจริงของ {ADF_STATE}")
    results.append(not base2)

    def mut2(label, change):
        t = copy.deepcopy(tree2)
        d2 = dict(downloads2)
        change(t, d2)
        if t == tree2 and d2 == downloads2:  # กันตัวควบคุมที่ไม่ได้แก้อะไรจริง (ผ่านแบบว่างเปล่า)
            raise RuntimeError(f"ตัวควบคุมไม่ได้เปลี่ยนผล: {label}")
        d = u.compare_state(refs[ADF_STATE], t, values2, d2)
        results.append(bool(d))
        print(("ตกตามคาด  " if d else "ไม่ตก (ผิดคาด) ") + label + (f" — {d[0]}" if d else ""))

    def adf_cell(t, d2):
        n = find(t["main"], lambda n: n.get("type") == "markdown" and "Level: t*" in n.get("body", ""))
        n["body"] = re.sub(r"(<td>-?\d+\.\d\d)(\d)(</td>)", lambda m: m.group(1) + str((int(m.group(2)) + 1) % 10)
                           + m.group(3), n["body"], count=1)

    def diag_label(t, d2):
        n = find(t["main"], lambda n: n.get("type") == "markdown" and "diag-table" in n.get("body", ""))
        # หน้าเดิมตัดบรรทัดชื่อหมวดเป็น "Stationarity<br>(Long-run)" — เปลี่ยนกลับเป็นชื่อหมวดของ e6aee03
        n["body"] = n["body"].replace("Stationarity<br>(Long-run)", "Stationarity", 1)

    def adf_csv(t, d2):
        n = find(t["main"], lambda n: n.get("type") == "download_button" and "ADF" in n.get("label", ""))
        d2["<แก้แล้ว>"] = (d2[n["ref"]][0] + b" ", *d2[n["ref"]][1:])
        n["ref"] = "<แก้แล้ว>"

    mut2("ค่า t* ในตาราง ADF รายตัวแปร (ทศนิยมตำแหน่งที่ 3)", adf_cell)
    mut2("ชื่อหมวด Stationarity (Long-run) ในตาราง diagnostics", diag_label)
    mut2("เนื้อไฟล์ CSV ตาราง ADF ต่าง 1 byte", adf_csv)
    ok = sum(results)
    print(f"\nสรุป: ตามคาด {ok}/{len(results)}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
