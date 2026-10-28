"""st.rerun()/st.stop() ใน st ตัวแทน (app/ui.py) ต้องทำงานแบบ Streamlit 1.64: RerunException/StopException สืบจาก
BaseException (ScriptControlException) จึงหลุดผ่าน except Exception ในโค้ดหน้าเดิมได้ — หน้าจัดการข้อมูลเดิมเรียก st.rerun()
ใน try/except Exception หลังดึงข้อมูลสำเร็จ (TFP_App1.3.0.py:6655-6665)"""
from app import ui


def _run(script):
    page = ui.PageRun({}, {}, None, lambda data, name, mime: "ref", lambda: {})
    page.execute(script)
    return page


def test_same_base_class_as_streamlit():
    # import ในฟังก์ชัน: test_parity_core ตรวจว่า process ไม่ได้โหลด streamlit ระหว่างคำนวณ (แบบเดียวกับ ui_parity.py)
    from streamlit.runtime.scriptrunner_utils.exceptions import RerunException, StopException

    for theirs, ours in ((RerunException, ui.RerunRun), (StopException, ui.StopRun)):
        assert issubclass(theirs, BaseException) and not issubclass(theirs, Exception)
        assert issubclass(ours, BaseException) and not issubclass(ours, Exception)


def test_rerun_inside_except_exception_still_reruns():
    def script(st):
        st.session_state.rounds = st.session_state.get("rounds", 0) + 1
        if st.session_state.rounds == 1:
            try:
                st.session_state.data = "ข้อมูลที่เพิ่งดึง"
                st.rerun()
            except Exception:
                st.session_state.pop("data", None)

    page = _run(script)
    assert page.values["rounds"] == 2 and page.values["data"] == "ข้อมูลที่เพิ่งดึง"


def test_stop_inside_except_exception_still_stops():
    def script(st):
        try:
            st.stop()
        except Exception:
            st.markdown("ไม่ควรถึงตรงนี้")
        st.markdown("ไม่ควรถึงตรงนี้เช่นกัน")

    page = _run(script)
    assert page.main["children"] == []
