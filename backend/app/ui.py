"""ตัวแทน `st` สำหรับรันโค้ดหน้าเดิม (page_script.py) ฝั่ง server แล้วได้ element tree ให้ React แสดง

รองรับเฉพาะ API ของ Streamlit ที่หน้าเดิมใช้ และเลียนกติกาของ Streamlit 1.64 ที่มีผลต่อสิ่งที่ผู้ใช้เห็น:
- markdown/caption/alert เก็บข้อความหลัง dedent+strip (clean_text) เหมือน Streamlit
- widget: ค่าอยู่ใน session_state ตาม key (ไม่มี key ใช้ id ที่คำนวณจากพารามิเตอร์) ลำดับความสำคัญ:
  ค่าที่ผู้ใช้เพิ่งเปลี่ยน > ค่าที่ค้างใน session > ค่าเริ่มต้น
- ปุ่มเป็น trigger: True เฉพาะรอบที่ถูกกด; ฟอร์มส่งค่าของ widget ในฟอร์มพร้อมปุ่ม submit เท่านั้น
- รันจบปกติ: ลบ state ของ widget ที่ไม่ถูกสร้างในรอบนั้น; st.rerun()/st.stop(): ไม่ลบ (เหมือน Streamlit)
- ช่อง password ใช้ค่าที่ส่งมาเฉพาะรอบนั้น ไม่เก็บใน session และไม่ส่งกลับ
ไม่มีการคำนวณโมเดลหรือเรียกบริการภายนอกในไฟล์นี้
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import textwrap
import threading
import uuid
from typing import Any, Callable

import altair as alt
import pandas as pd

log = logging.getLogger("tfp.page")
_ALTAIR_LOCK = threading.Lock()  # theme/data transformer ของ Altair เป็นค่ากลางของ process

MAX_RERUNS = 10  # กันวนไม่รู้จบ (หน้าเดิมเรียก st.rerun() หลังเปลี่ยนสถานะเท่านั้น)


class StopRun(BaseException):
    """st.stop() — BaseException เหมือน StopException ของ Streamlit 1.64 (ScriptControlException) ไม่ให้ except Exception ในหน้าเดิมจับ"""


class RerunRun(BaseException):
    """st.rerun() — BaseException เหมือน RerunException ของ Streamlit 1.64 (หน้าเดิมเรียก st.rerun() ใน try/except Exception
    ที่ TFP_App1.3.0.py:6662 หลังดึงข้อมูลในหน้าจัดการข้อมูล ถ้าเป็น Exception จะถูกจับแล้วข้อมูลที่เพิ่งดึงถูกลบ)"""


class EventError(ValueError):
    """event จากหน้าเว็บไม่ตรงกับ widget ที่มีอยู่หรือค่าผิดชนิด/ผิดช่วง"""


class Pending(BaseException):
    """ผลที่หน้าต้องใช้ยังไม่พร้อม (worker กำลังทำ job) — BaseException เพื่อไม่ให้ except Exception ในหน้าเดิมจับ

    job_id: job ที่ต้องรอ · trigger: ปุ่มที่ต้องกดซ้ำให้เมื่อ job เสร็จ (None ถ้าแค่รันหน้าใหม่)
    """

    def __init__(self, job_id, trigger=None, kind=None, spinner=""):
        super().__init__(job_id)
        self.job_id, self.trigger, self.kind, self.spinner = job_id, trigger, kind, spinner


def clean_text(text) -> str:
    return textwrap.dedent(str(text)).strip()


def extract_leading_icon(text: str) -> tuple[str, str]:
    """อีโมจินำหน้าข้อความของ alert (Streamlit 1.64 string_util.extract_leading_icon ส่วนอีโมจิ)"""
    if not text or text.isascii():
        return "", text
    if text.startswith(":material"):
        raise NotImplementedError("หน้าเดิมไม่มีข้อความ alert ที่ขึ้นต้นด้วย material icon")
    from .vendor.streamlit_emojis import EMOJI_EXTRACTION_REGEX

    m = EMOJI_EXTRACTION_REGEX.search(text)
    return ("", text) if m is None else (m.group(1), m.group(2))


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EventError("ค่าต้องเป็นตัวเลข")
    if isinstance(v, float) and not math.isfinite(v):
        raise EventError("ค่าต้องเป็นตัวเลขจำกัด")
    return v


class SessionState:
    """st.session_state: อ่าน/เขียนได้ทั้งแบบ attribute และ key"""

    def __init__(self, runner: "PageRun"):
        object.__setattr__(self, "_run", runner)

    def _store(self):
        return self._run.values

    def __getattr__(self, name):
        try:
            return self._store()[name]
        except KeyError:
            raise AttributeError(f'st.session_state has no attribute "{name}"') from None

    def __setattr__(self, name, value):
        self[name] = value

    def __getitem__(self, key):
        return self._store()[key]

    def __setitem__(self, key, value):
        if key in self._run.registered:
            raise RuntimeError(f"st.session_state.{key} cannot be modified after the widget with key {key} "
                               "is instantiated.")
        self._store()[key] = value

    def __delitem__(self, key):
        del self._store()[key]

    def __delattr__(self, name):
        del self[name]

    def __contains__(self, key):
        return key in self._store()

    def get(self, key, default=None):
        return self._store().get(key, default)

    def pop(self, key, *default):
        return self._store().pop(key, *default)

    def setdefault(self, key, default=None):
        return self._store().setdefault(key, default)

    def keys(self):
        return self._store().keys()

    def items(self):
        return self._store().items()


class Block:
    """กล่องที่ใช้กับ with (container/column/expander/form/sidebar)"""

    def __init__(self, run: "PageRun", node: dict, form_id: str | None = None):
        self._run, self.node, self.form_id = run, node, form_id

    def __enter__(self):
        self._run.stack.append(self)
        return self

    def __exit__(self, *exc):
        self._run.stack.pop()
        return False


class PageRun:
    """หนึ่งการเรียกหน้า (อาจรันสคริปต์ซ้ำหลายรอบถ้ามี st.rerun())

    values: dict ของ session_state (แก้ในที่) · widget_ids: id ของ widget ที่มีอยู่จากรอบก่อน (ใช้ตรวจ event)
    event: {"trigger": id หรือ None, "values": {id: ค่า}} จากหน้าเว็บ
    register_download(data, file_name, mime) -> ref ของไฟล์ให้ดาวน์โหลด
    """

    def __init__(self, values: dict, widget_meta: dict, event: dict | None,
                 register_download: Callable[[bytes, str, str], str], secrets: Callable[[], dict]):
        self.values = values
        self.prev_meta = widget_meta or {}
        self.event = event or {}
        self.register_download = register_download
        self._secrets = secrets
        self.page_config: dict = {}
        self.session_state = SessionState(self)
        self.reruns = 0
        self.pending: dict | None = None
        self.error_ref: str | None = None

    # ----- รอบการรัน -----
    def execute(self, script: Callable[["PageRun"], None]) -> dict:
        self._validate_event()
        fresh = dict(self.event.get("values") or {})
        trigger = self.event.get("trigger")
        while True:
            self._start_round(fresh, trigger)
            try:
                script(self)
                self._finish_round(remove_stale=True)
                break
            except StopRun:
                self._finish_round(remove_stale=False)
                break
            except RerunRun:
                self._finish_round(remove_stale=False)
                self.reruns += 1
                if self.reruns > MAX_RERUNS:
                    raise RuntimeError("st.rerun() เกินจำนวนรอบที่กำหนด")
                fresh, trigger = {}, None
            except Pending as p:
                # แสดงสิ่งที่วาดได้แล้ว + spinner ตำแหน่งเดิม แล้วรอ job (ไม่ลบ state เหมือนหยุดกลางรอบ)
                self._add({"type": "spinner", "text": p.spinner})
                self.pending = {"job_id": p.job_id, "trigger": p.trigger, "kind": p.kind}
                self._finish_round(remove_stale=False)
                break
            except Exception:
                # Streamlit แสดง traceback ให้ผู้ใช้ — ระบบใหม่ไม่เผยรายละเอียด (§20.3) บันทึกใน log แทน
                self.error_ref = uuid.uuid4().hex[:12]
                log.exception("page run failed ref=%s", self.error_ref)
                self._add({"type": "exception", "ref": self.error_ref})
                self._finish_round(remove_stale=False)
                break
        return {"main": self.main, "sidebar": self.sidebar_node, "page_config": self.page_config,
                "pending": self.pending}

    def _start_round(self, fresh: dict, trigger):
        self.main = {"type": "main", "children": []}
        self.sidebar_node = {"type": "sidebar", "children": []}
        self.stack = [Block(self, self.main)]
        self.registered: set = set()
        self.meta: dict = {}
        self.fresh, self.trigger = fresh, trigger
        self.spinners: list = []
        self.options: dict = {}  # ค่าจริงของตัวเลือก (ไม่ส่งให้หน้าเว็บ หน้าเว็บส่งเลขลำดับ)

    def _finish_round(self, remove_stale: bool):
        # ค่าของช่อง password ไม่เก็บข้ามรอบ
        for wid, m in self.meta.items():
            if m.get("secret"):
                self.values.pop(wid, None)
        if remove_stale:
            known = set(self.prev_meta) | set(self.meta)
            for wid in known - self.registered:
                self.values.pop(wid, None)
            self.prev_meta = dict(self.meta)
        else:
            self.prev_meta = {**self.prev_meta, **self.meta}

    def _validate_event(self):
        """event ต้องอ้าง widget ที่มีอยู่จากรอบก่อน และค่าต้องผ่านข้อจำกัดของ widget นั้น"""
        trig = self.event.get("trigger")
        if trig is not None:
            m = self.prev_meta.get(trig)
            if not m or m["kind"] not in ("button", "form_submit", "download"):
                raise EventError("ไม่พบปุ่มที่อ้างถึง")
        for wid, v in (self.event.get("values") or {}).items():
            m = self.prev_meta.get(wid)
            if not m or m["kind"] in ("button", "form_submit", "download"):
                raise EventError("ไม่พบช่องที่อ้างถึง")
            if m.get("form") and (trig is None or self.prev_meta[trig].get("form") != m["form"]):
                raise EventError("ช่องในฟอร์มส่งได้พร้อมปุ่มส่งฟอร์มเท่านั้น")
            _check_value(m, v)

    # ----- ตำแหน่งที่วาง element -----
    @property
    def _block(self) -> Block:
        return self.stack[-1]

    def _form_id(self):
        for b in reversed(self.stack):
            if b.form_id:
                return b.form_id
        return None

    def _add(self, node: dict) -> dict:
        self._block.node["children"].append(node)
        return node

    def _add_block(self, node: dict, form_id=None) -> Block:
        node.setdefault("children", [])
        self._add(node)
        return Block(self, node, form_id)

    # ----- widget state -----
    def _widget_id(self, kind: str, key, label, **params) -> str:
        if key is not None:
            wid = str(key)
        else:
            h = hashlib.sha1(kind.encode("utf-8"))
            h.update(str(label).encode("utf-8"))
            h.update(str(self._form_id()).encode("utf-8"))
            for k, v in params.items():
                h.update(f"{k}={v!r}".encode("utf-8"))
            wid = f"$$auto-{kind}-{h.hexdigest()[:16]}"
        if wid in self.registered:
            raise RuntimeError(f"widget id ซ้ำ: {wid}")
        self.registered.add(wid)
        return wid

    def _value(self, wid: str, meta: dict, default, valid: Callable[[Any], bool]):
        """ค่าของ widget ในรอบนี้ ตามลำดับ: ค่าใหม่จากผู้ใช้ > ค่าค้างใน session > ค่าเริ่มต้น"""
        form = meta.get("form")
        if wid in self.fresh and (form is None or (self.trigger and self.prev_meta.get(self.trigger, {}).get("form") == form)):
            v = self.fresh[wid]
            value = meta["decode"](v) if "decode" in meta else v
        elif wid in self.values and valid(self.values[wid]):
            value = self.values[wid]
        else:
            value = default
        if not valid(value):
            value = default
        self.values[wid] = value
        self.meta[wid] = {k: v for k, v in meta.items() if k != "decode"}
        return value

    def _trigger(self, wid: str, kind: str, form=None) -> bool:
        self.meta[wid] = {"kind": kind, "form": form}
        return self.trigger == wid

    # ===================== API แบบ st =====================
    def set_page_config(self, **kwargs):
        self.page_config = {k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool, type(None)))}

    @property
    def secrets(self):
        return self._secrets()

    @property
    def sidebar(self) -> Block:
        return Block(self, self.sidebar_node)

    def cache_data(self, *dargs, **dkwargs):  # หน้าเดิมไม่เหลือการใช้ cache หลังย้าย — คงไว้กันพลาด
        if dargs and callable(dargs[0]):
            return dargs[0]
        return lambda f: f

    @contextlib.contextmanager
    def spinner(self, text="In progress...", **kwargs):
        # spinner เป็น element ชั่วคราว ไม่อยู่ในผลสุดท้าย (Streamlit 1.64 _transient)
        # จำข้อความไว้ใช้แสดงตอนต้องรอ job ภายในบล็อกนี้
        self.spinners.append(clean_text(text))
        try:
            yield
        finally:
            self.spinners.pop()

    def rerun(self, **kwargs):
        raise RerunRun()

    def stop(self):
        raise StopRun()

    # ----- ข้อความ -----
    def markdown(self, body, unsafe_allow_html=False, help=None, **kwargs):
        self._add({"type": "markdown", "body": clean_text(body), "allow_html": bool(unsafe_allow_html),
                   "kind": "markdown", "help": help})

    def caption(self, body, unsafe_allow_html=False, help=None, **kwargs):
        self._add({"type": "markdown", "body": clean_text(body), "allow_html": bool(unsafe_allow_html),
                   "kind": "caption", "help": help})

    def write(self, *args, unsafe_allow_html=False):
        if not all(isinstance(a, str) for a in args):
            raise NotImplementedError("หน้าเดิมใช้ st.write กับข้อความเท่านั้น")
        self.markdown(" ".join(args), unsafe_allow_html=unsafe_allow_html)

    def _alert(self, kind, body, icon=None, **kwargs):
        body = clean_text(body)
        if icon is None:
            icon, body = extract_leading_icon(body)
        self._add({"type": "alert", "kind": kind, "body": body, "icon": icon or None})

    def info(self, body, icon=None, **kwargs):
        self._alert("info", body, icon)

    def success(self, body, icon=None, **kwargs):
        self._alert("success", body, icon)

    def warning(self, body, icon=None, **kwargs):
        self._alert("warning", body, icon)

    def error(self, body, icon=None, **kwargs):
        self._alert("error", body, icon)

    # ----- กล่อง -----
    def container(self, border=None, key=None, height=None, **kwargs) -> Block:
        return self._add_block({"type": "container", "key": key, "border": bool(border), "height": height})

    def columns(self, spec, gap="small", vertical_alignment="top", border=False, **kwargs):
        weights = [1] * spec if isinstance(spec, int) else list(spec)
        weights = [w / sum(weights) for w in weights]  # Streamlit เก็บน้ำหนักแบบหารผลรวม
        row = self._add_block({"type": "columns", "gap": gap, "vertical_alignment": vertical_alignment,
                               "border": bool(border)})
        cols = []
        for w in weights:
            node = {"type": "column", "weight": w, "children": []}
            row.node["children"].append(node)
            cols.append(Block(self, node))
        return cols

    def expander(self, label, expanded=False, key=None, icon=None, **kwargs) -> Block:
        return self._add_block({"type": "expander", "label": clean_text(label), "expanded": bool(expanded),
                                "key": key, "icon": icon})

    def form(self, key, clear_on_submit=False, border=True, **kwargs) -> Block:
        return self._add_block({"type": "form", "form_id": key, "border": bool(border)}, form_id=key)

    # ----- กราฟ ตาราง ไฟล์ -----
    def altair_chart(self, chart, use_container_width=None, theme="streamlit", key=None, **kwargs):
        self._add({"type": "vega_lite_chart", "spec": vega_spec(chart), "use_container_width": bool(use_container_width),
                   "theme": theme})

    def dataframe(self, data, use_container_width=None, hide_index=None, **kwargs):
        df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
        self._add({"type": "dataframe", "columns": [str(c) for c in df.columns],
                   "index": None if hide_index else [_json_value(i) for i in df.index],
                   "rows": [[_json_value(v) for v in row] for row in df.itertuples(index=False, name=None)],
                   "use_container_width": bool(use_container_width)})

    def download_button(self, label, data, file_name=None, mime=None, key=None, help=None, type="secondary",
                        icon=None, disabled=False, use_container_width=False, on_click="rerun", **kwargs):
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        mime = mime or ("text/plain" if isinstance(data, str) else "application/octet-stream")
        wid = self._widget_id("download_button", key, label, file_name=file_name, mime=mime,
                              sha=hashlib.sha256(raw).hexdigest())
        ref = self.register_download(raw, file_name or "download", mime)
        self._trigger(wid, "download")
        self._add({"type": "download_button", "id": wid, "label": label, "file_name": file_name, "mime": mime,
                   "ref": ref, "kind": type, "icon": icon, "disabled": bool(disabled), "help": help,
                   "use_container_width": bool(use_container_width)})
        return self.trigger == wid

    # ----- widget -----
    def button(self, label, key=None, help=None, type="secondary", icon=None, disabled=False,
               use_container_width=False, **kwargs) -> bool:
        form = self._form_id()
        if form:
            raise RuntimeError("st.button ใช้ในฟอร์มไม่ได้")
        wid = self._widget_id("button", key, label, help=help, type=type, icon=icon)
        pressed = self._trigger(wid, "button")
        self._add({"type": "button", "id": wid, "label": label, "kind": type, "icon": icon, "help": help,
                   "disabled": bool(disabled), "use_container_width": bool(use_container_width)})
        return pressed

    def form_submit_button(self, label="Submit", help=None, type="secondary", icon=None, disabled=False,
                           use_container_width=False, key=None, **kwargs) -> bool:
        form = self._form_id()
        if not form:
            raise RuntimeError("st.form_submit_button ต้องอยู่ในฟอร์ม")
        # Streamlit 1.64 (elements/form.py:478): ปุ่ม submit ที่ไม่ได้ตั้ง key ใช้ key "FormSubmitter:<form>-<label>"
        user_key = (str(key) if key is not None else None) or f"FormSubmitter:{form}-{label}"
        wid = self._widget_id("form_submit_button", user_key, label, form=form, help=help, type=type)
        pressed = self._trigger(wid, "form_submit", form)
        self._add({"type": "button", "id": wid, "label": label, "kind": type, "icon": icon, "help": help,
                   "disabled": bool(disabled), "use_container_width": bool(use_container_width),
                   "form_id": form, "is_form_submitter": True})
        return pressed

    def selectbox(self, label, options, index=0, format_func=str, key=None, help=None, on_change=None,
                  disabled=False, label_visibility="visible", placeholder=None, **kwargs):
        opts = list(options)
        default = opts[index] if index is not None and opts else None
        form = self._form_id()
        wid = self._widget_id("selectbox", key, label, options=tuple(map(str, opts)), index=index, help=help,
                              form=form)
        meta = {"kind": "selectbox", "n": len(opts), "form": form, "nullable": index is None,
                "decode": lambda i: None if i is None else opts[i]}
        value = self._value(wid, meta, default, lambda v: (v is None and index is None) or v in opts)
        self.options[wid] = opts
        self._add({"type": "selectbox", "id": wid, "label": label, "options": [str(format_func(o)) for o in opts],
                   "index": None if value is None else opts.index(value), "default": index, "help": help,
                   "disabled": bool(disabled), "label_visibility": label_visibility, "placeholder": placeholder,
                   "form_id": form})
        return value

    def multiselect(self, label, options, default=None, format_func=str, key=None, help=None, on_change=None,
                    disabled=False, label_visibility="visible", placeholder=None, max_selections=None, **kwargs):
        opts = list(options)
        dflt = list(default or [])
        form = self._form_id()
        wid = self._widget_id("multiselect", key, label, options=tuple(map(str, opts)),
                              default=tuple(map(str, dflt)), help=help, form=form)
        meta = {"kind": "multiselect", "n": len(opts), "form": form, "decode": lambda idx: [opts[i] for i in idx]}
        value = self._value(wid, meta, dflt, lambda v: isinstance(v, list) and all(x in opts for x in v))
        self.options[wid] = opts
        self._add({"type": "multiselect", "id": wid, "label": label, "options": [str(format_func(o)) for o in opts],
                   "value": [opts.index(v) for v in value], "default": [opts.index(v) for v in dflt if v in opts],
                   "help": help, "disabled": bool(disabled), "label_visibility": label_visibility,
                   "placeholder": placeholder, "form_id": form})
        return list(value)

    def number_input(self, label, min_value=None, max_value=None, value="min", step=None, format=None, key=None,
                     help=None, on_change=None, disabled=False, label_visibility="visible", placeholder=None,
                     **kwargs):
        if value == "min":
            value = min_value if min_value is not None else 0.0
        is_int = all(isinstance(x, int) and not isinstance(x, bool) for x in (value, min_value, max_value, step)
                     if x is not None)
        if step is None:
            step = 1 if is_int else 0.01
        if format is None:
            format = "%d" if is_int else "%0.2f"
        form = self._form_id()
        wid = self._widget_id("number_input", key, label, min_value=min_value, max_value=max_value, value=value,
                              step=step, format=format, help=help, form=form)

        def ok(v):
            return (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                    and (min_value is None or v >= min_value) and (max_value is None or v <= max_value))

        meta = {"kind": "number_input", "min": min_value, "max": max_value, "int": is_int, "form": form,
                "decode": (lambda v: int(v)) if is_int else (lambda v: float(v))}
        cur = self._value(wid, meta, value, ok)
        self._add({"type": "number_input", "id": wid, "label": label, "value": cur, "default": value,
                   "min": min_value, "max": max_value, "step": step, "format": format, "int": is_int, "help": help,
                   "disabled": bool(disabled), "label_visibility": label_visibility, "placeholder": placeholder,
                   "form_id": form})
        return cur

    def slider(self, label, min_value=None, max_value=None, value=None, step=None, format=None, key=None,
               help=None, on_change=None, disabled=False, label_visibility="visible", **kwargs):
        if value is None:
            value = min_value
        if isinstance(value, (list, tuple)):
            raise NotImplementedError("หน้าเดิมใช้ slider ค่าเดียว")
        is_int = all(isinstance(x, int) and not isinstance(x, bool) for x in (min_value, max_value, value))
        if step is None:
            step = 1 if is_int else 0.01
        if format is None:
            format = "%d" if is_int else "%0.2f"
        form = self._form_id()
        wid = self._widget_id("slider", key, label, min_value=min_value, max_value=max_value, value=value,
                              step=step, format=format, help=help, form=form)

        def ok(v):
            return (isinstance(v, (int, float)) and not isinstance(v, bool) and min_value <= v <= max_value
                    and (not is_int or float(v).is_integer()))

        meta = {"kind": "slider", "min": min_value, "max": max_value, "int": is_int, "form": form,
                "decode": (lambda v: int(v)) if is_int else (lambda v: float(v))}
        cur = self._value(wid, meta, value, ok)
        self._add({"type": "slider", "id": wid, "label": label, "value": cur, "default": value, "min": min_value,
                   "max": max_value, "step": step, "format": format, "int": is_int, "help": help,
                   "disabled": bool(disabled), "label_visibility": label_visibility, "form_id": form})
        return cur

    def toggle(self, label, value=False, key=None, help=None, on_change=None, disabled=False,
               label_visibility="visible", **kwargs):
        form = self._form_id()
        wid = self._widget_id("toggle", key, label, value=value, help=help, form=form)
        cur = self._value(wid, {"kind": "toggle", "form": form}, bool(value), lambda v: isinstance(v, bool))
        self._add({"type": "toggle", "id": wid, "label": label, "value": cur, "default": bool(value), "help": help,
                   "disabled": bool(disabled), "label_visibility": label_visibility, "form_id": form})
        return cur

    def _text(self, kind, label, value, max_chars, key, type_, help, placeholder, label_visibility, disabled,
              autocomplete=None, height=None):
        form = self._form_id()
        wid = self._widget_id(kind, key, label, value=value, max_chars=max_chars, type=type_, help=help,
                              placeholder=placeholder, form=form)
        limit = max_chars or 10_000
        meta = {"kind": kind, "max_chars": limit, "form": form, "secret": type_ == "password"}
        cur = self._value(wid, meta, value or "", lambda v: isinstance(v, str) and len(v) <= limit)
        self._add({"type": kind, "id": wid, "label": label, "value": "" if type_ == "password" else cur,
                   "default": value or "", "max_chars": max_chars, "input_type": type_, "help": help,
                   "placeholder": placeholder, "label_visibility": label_visibility, "disabled": bool(disabled),
                   "autocomplete": autocomplete, "height": height, "form_id": form})
        return cur

    def text_input(self, label, value="", max_chars=None, key=None, type="default", help=None, autocomplete=None,
                   on_change=None, placeholder=None, disabled=False, label_visibility="visible", **kwargs):
        return self._text("text_input", label, value, max_chars, key, type, help, placeholder, label_visibility,
                          disabled, autocomplete=autocomplete)

    def text_area(self, label, value="", height=None, max_chars=None, key=None, help=None, on_change=None,
                  placeholder=None, disabled=False, label_visibility="visible", **kwargs):
        return self._text("text_area", label, value, max_chars, key, "default", help, placeholder,
                          label_visibility, disabled, height=height)


def vega_spec(chart) -> dict:
    """spec แบบที่ Streamlit 1.64 ส่งให้หน้าเว็บ (streamlit/elements/vega_charts.py):
    ปิด theme default ของ Altair ตอน to_dict, autosize = fit/padding (กราฟชั้นเดียวหรือ layer),
    แทน title ว่าง (null) ของ legend สีระดับบนด้วยช่องว่าง ข้อมูลยังฝังเป็น datasets ของ Altair"""
    with _ALTAIR_LOCK:
        ctx = alt.theme.enable("none") if alt.theme.active == "default" else contextlib.nullcontext()
        with ctx:
            spec = chart.to_dict()
    if "autosize" not in spec:
        if "vconcat" in spec or "facet" in spec or any(
                k in spec.get("encoding", {}) for k in ("row", "column", "facet")):
            raise NotImplementedError("หน้าเดิมไม่มีกราฟ vconcat/facet")
        spec["autosize"] = {"type": "fit", "contains": "padding"}
    color = spec.get("encoding", {}).get("color") if isinstance(spec.get("encoding"), dict) else None
    if isinstance(color, dict):
        if "title" in color and color["title"] is None:
            color["title"] = " "
        if isinstance(color.get("legend"), dict) and "title" in color["legend"] and color["legend"]["title"] is None:
            color["legend"]["title"] = " "
    return spec


def _check_value(meta: dict, v):
    kind = meta["kind"]
    if kind == "selectbox":
        if v is None and meta.get("nullable"):
            return
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < meta["n"]:
            raise EventError("ตัวเลือกไม่ถูกต้อง")
    elif kind == "multiselect":
        if not isinstance(v, list) or len(set(v)) != len(v) or any(
                isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < meta["n"] for i in v):
            raise EventError("ตัวเลือกไม่ถูกต้อง")
    elif kind in ("number_input", "slider"):
        _num(v)
        if meta["int"] and not float(v).is_integer():
            raise EventError("ค่าต้องเป็นจำนวนเต็ม")
        if (meta.get("min") is not None and v < meta["min"]) or (meta.get("max") is not None and v > meta["max"]):
            raise EventError("ค่าอยู่นอกช่วงที่กำหนด")
    elif kind == "toggle":
        if not isinstance(v, bool):
            raise EventError("ค่าต้องเป็นจริง/เท็จ")
    elif kind in ("text_input", "text_area"):
        if not isinstance(v, str) or len(v) > meta["max_chars"]:
            raise EventError("ข้อความยาวเกินกำหนดหรือผิดชนิด")
    else:
        raise EventError("ชนิดช่องไม่รองรับ")


def _json_value(v):
    if v is None:
        return None
    if isinstance(v, (bool,)):
        return v
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (int, str)):
        return v
    if v is pd.NA or v is pd.NaT:
        return None
    return str(v)
