"""รันโค้ดหน้าเดิม (page_script.py) หนึ่งคำขอ แล้วคืน element tree + สถานะ session ที่ต้องเก็บ

session ที่เก็บ (JSON): values (session_state ผ่าน codec ยกเว้นข้อมูลชีตที่เก็บเป็น dataset_id), widget_meta
(widget ของรอบล่าสุด ใช้ตรวจ event), pending (job ที่หน้ารออยู่ และปุ่มที่ต้องกดซ้ำเมื่อ job เสร็จ)
store คือที่เก็บข้อมูล/ผล/job (Postgres ในระบบจริง, หน่วยความจำใน test) — ดู store_memory.py / db.py
"""
from __future__ import annotations

import base64
import builtins
import datetime
import html
import hashlib
import re
import time
from pathlib import Path

from . import codec, compute, page_api
from .ui import Pending, PageRun

APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR / "assets"
_SCRIPT = compile((APP_DIR / "page_script.py").read_text(encoding="utf-8"), str(APP_DIR / "page_script.py"), "exec")
DATA_KEY = "gsheet_raw_df"  # session_state ที่เก็บข้อมูลชีต (TFP_App1.3.0.py:3225)
TH_TZ = datetime.timezone(datetime.timedelta(hours=7))  # เขตเวลาของหน้าเดิม (TFP_App1.3.0.py:41)


class PageContext:
    """ค่าของหนึ่งคำขอที่ page_api ใช้"""

    def __init__(self, store, session_id: str, run: PageRun, resume: dict | None, fetch_per_hour: int | None,
                 max_pending_fetch: int | None = None):
        self.store, self.session_id, self.st = store, session_id, run
        self.fetch_per_hour, self.max_pending_fetch = fetch_per_hour, max_pending_fetch
        self.resume = resume
        self.resumed = False
        self.datasets: dict = {}      # id(DataFrame) → dataset_id (ข้อมูลชีตของ session หรือที่เพิ่งดึง)
        self.model_frames: dict = {}  # id(model_df) → dataset_id
        self.resids: dict = {}
        self.keep: list = []          # ให้ id() ของวัตถุข้างบนไม่ถูกใช้ซ้ำระหว่างคำขอ
        self.clock_shift = None       # หลังได้ข้อมูลจากงานดึงชีต: เวลาอ่านชีตสำเร็จ − เวลาตอนรับผล (page_api._page_clock)
        self._ecm: dict = {}
        self._series: dict = {}
        # งานต่อกันของการกดครั้งเดียว (สรุป Gemini → Word → PowerPoint): ทุกครั้งที่ resume หน้าเดิมรันใหม่ตั้งแต่ต้น
        # จึงใช้ job ตามลำดับที่สร้างไว้แล้ว ไม่สร้างใหม่ (ไม่เรียก Gemini ซ้ำ) — เก็บใน pending["chain"] ระหว่าง resume
        self.chain: list = list(resume.get("chain") or []) if resume else []
        self._chain_pos = 0

    def dataset_of(self, df):
        return self.datasets.get(id(df))

    def adopt_dataset(self, df, dataset_id):
        self.datasets[id(df)] = dataset_id
        self.keep.append(df)
        return df

    # ----- job -----
    def _wait(self, kind: str, params: dict, trigger=None):
        """job ที่หน้ารออยู่: ถ้ากำลัง resume job เดียวกันใช้ผลนั้น ไม่งั้นสร้าง/ใช้ job ที่ตรงกัน"""
        r = self.resume
        if r and r.get("kind") == kind and r.get("trigger") == trigger and not self.resumed:
            job_id = r["job_id"]
        else:
            job_id = self.store.start_job(self.session_id, kind, params)
        job = self.store.job(job_id)
        if job["status"] in ("queued", "running"):
            # ข้อความ spinner ของบล็อกที่กำลังรอ (หน้าเดิมแสดงระหว่างคำนวณ)
            raise Pending(job_id, trigger, kind, self.st.spinners[-1] if self.st.spinners else "")
        if r and r.get("job_id") == job_id:
            self.resumed = True
        return job

    def _wait_chain(self, kind: str, params: dict):
        if self._chain_pos < len(self.chain):
            entry = self.chain[self._chain_pos]
            if entry["kind"] != kind:
                raise RuntimeError("ลำดับงานของการกดครั้งนี้ไม่ตรงกับรอบก่อน")
            job_id = entry["job_id"]
        else:
            job_id = self.store.start_job(self.session_id, kind, params)
            self.chain.append({"kind": kind, "job_id": job_id})
        self._chain_pos += 1
        job = self.store.job(job_id)
        if job["status"] in ("queued", "running"):
            raise Pending(job_id, self.st.trigger, kind, self.st.spinners[-1] if self.st.spinners else "")
        return job

    def ecm_bundle(self, dataset_id, lr_vars):
        sr_spec = list(self.st.values.get("active_short_run_spec") or [])
        key = (dataset_id, tuple(lr_vars), tuple(tuple(s) for s in sr_spec))
        if key not in self._ecm:
            b = self.store.ecm(dataset_id, lr_vars, sr_spec)
            if b is None:
                job = self._wait("ecm", {"dataset_id": dataset_id, "lr_vars": list(lr_vars),
                                         "sr_spec": [list(s) for s in sr_spec]})
                if job["status"] != "succeeded":
                    raise RuntimeError(f"job ecm ไม่สำเร็จ: {job.get('error')}")
                b = self.store.ecm(dataset_id, lr_vars, sr_spec)
            self._ecm[key] = b
        return self._ecm[key]

    def has_series_bundle(self, series) -> bool:
        """มีผล backtest ของข้อมูลชุดนี้ใน DB แล้วหรือยัง — ไม่สร้าง job (page_api._bt_cache_has, 4c8aa71)"""
        dataset_id = self.dataset_of(self.st.values.get(DATA_KEY))
        page_api._require(dataset_id is not None, "ไม่มีข้อมูลของ session")
        if dataset_id not in self._series:
            b = self.store.series(dataset_id)
            if b is None:
                return False
            self._series[dataset_id] = b
        page_api._require(codec.encode(series) == codec.encode(self._series[dataset_id]["tfp_series"]),
                          "อนุกรม TFP ไม่ตรงกับที่คำนวณไว้")
        return True

    def series_bundle(self, series):
        dataset_id = self.dataset_of(self.st.values.get(DATA_KEY))
        page_api._require(dataset_id is not None, "ไม่มีข้อมูลของ session")
        if dataset_id not in self._series:
            b = self.store.series(dataset_id)
            if b is None:
                job = self._wait("series", {"dataset_id": dataset_id})
                if job["status"] != "succeeded":
                    raise RuntimeError(f"job series ไม่สำเร็จ: {job.get('error')}")
                b = self.store.series(dataset_id)
            self._series[dataset_id] = b
        b = self._series[dataset_id]
        page_api._require(codec.encode(series) == codec.encode(b["tfp_series"]), "อนุกรม TFP ไม่ตรงกับที่คำนวณไว้")
        return b

    def fetch(self, url):
        r = self.resume
        resuming = bool(r and r.get("kind") == "fetch" and r.get("trigger") == self.st.trigger)
        if not resuming and self.fetch_per_hour is not None and \
                self.store.count_jobs(self.session_id, "fetch", 60) >= self.fetch_per_hour:
            # หน้าเดิมแสดงข้อความ exception ในแถบสถานะ "ดึงข้อมูลไม่สำเร็จ: ..." (TFP_App1.3.0.py:3230-3236)
            raise RuntimeError("ดึงข้อมูลบ่อยเกินกำหนดต่อชั่วโมง กรุณารอสักครู่แล้วลองใหม่")
        if not resuming and self.max_pending_fetch is not None and \
                self.store.count_pending("fetch") >= self.max_pending_fetch:
            raise RuntimeError("มีคำขอดึงข้อมูลรออยู่มากเกินกำหนด กรุณารอสักครู่แล้วลองใหม่")
        job = self._wait("fetch", {"url": url or None}, trigger=self.st.trigger)
        if job["status"] != "succeeded":
            # หน้าเดิมแทรกข้อความ error ลงใน HTML ของแถบสถานะ (unsafe_allow_html) และข้อความอาจมีลิงก์ที่ผู้ใช้กรอก
            # จึง escape < > & ก่อน (ข้อความปกติแสดงเหมือนเดิม) — แผน §20.3 XSS
            err = dict(job["error"], text=html.escape(job["error"]["text"], quote=False))
            raise compute.replay_error(err)
        dataset_id = job["result"]["dataset_id"]
        if job["result"].get("read_at") is not None:
            self.clock_shift = datetime.timedelta(seconds=job["result"]["read_at"] - time.time())
        return self.adopt_dataset(self.store.dataset(dataset_id), dataset_id)

    def summary(self, dataset_id, lr_vars, sr_spec):
        job = self._wait_chain("summary", {"dataset_id": dataset_id, "lr_vars": list(lr_vars),
                                           "sr_spec": [list(s) for s in sr_spec]})
        if job["status"] != "succeeded":
            raise compute.replay_error(job["error"])
        r = job["result"]
        # หน้าเดิมทำต่อทันทีหลัง Gemini ตอบ: เวลาของส่วนที่เหลือในคำขอนี้ (ข้อความ "สร้างเมื่อวันที่" ใต้บทสรุปและเวลาในไฟล์)
        # = เวลาที่ Gemini ตอบ ทุกครั้งที่ resume (แบบเดียวกับเวลาอ่านชีตของงานดึงข้อมูล)
        self.clock_shift = datetime.timedelta(seconds=r["done_at"] - time.time())
        for body in r["errors"]:  # ข้อความ st.error ของฟังก์ชันเดิม (Gemini ล้มเหลว) ตามด้วย st.stop()
            self.st.error(body)
        if r["stopped"]:
            self.st.stop()
        return r["text"]

    def report(self, kind, args, kwargs):
        now = page_api._page_clock(datetime.datetime.now(TH_TZ)).replace(tzinfo=None)
        job = self._wait_chain("report", {"report": kind, "args": codec.encode(list(args)),
                                          "kwargs": codec.encode(dict(kwargs)), "now": now.isoformat()})
        if job["status"] != "succeeded":
            raise compute.replay_error(job["error"])
        return base64.b64decode(job["result"]["b64"])


def run(store, session_id: str, state: dict, event: dict | None, secrets: dict, resume: bool = False,
        limits=None) -> dict:
    """รันหน้าหนึ่งคำขอ คืน {"tree", "state"} (state = session ที่ต้องเก็บกลับ)"""
    values = codec.decode(state["values"]) if state.get("values") else {}
    pending = state.get("pending") if resume else None
    if pending:
        event = {"trigger": pending.get("trigger")} if pending.get("trigger") else None
    downloads = []

    def register_download(data: bytes, file_name: str, mime: str) -> str:
        ref = store.put_download(session_id, data, file_name, mime)
        downloads.append(ref)
        return ref

    page = PageRun(values, state.get("widget_meta") or {}, event, register_download, lambda: secrets)
    ctx = PageContext(store, session_id, page, pending, getattr(limits, "fetch_per_hour", None),
                      getattr(limits, "max_pending_fetch", None))
    if state.get("dataset_id") is not None:
        values[DATA_KEY] = ctx.adopt_dataset(store.dataset(state["dataset_id"]), state["dataset_id"])

    def script(st):
        exec(_SCRIPT, {"__name__": "__main__", "__file__": str(ASSETS_DIR / "TFP_App1.3.0.py"),
                       "__builtins__": builtins, "st": st})

    token = page_api.CURRENT.set(ctx)
    try:
        tree = page.execute(script)
    finally:
        page_api.CURRENT.reset(token)

    dataset_id = None
    if DATA_KEY in values:
        dataset_id = ctx.dataset_of(values[DATA_KEY])
        if dataset_id is None:
            raise RuntimeError("ข้อมูลชีตใน session ไม่ได้มาจาก dataset ที่เก็บไว้")
    kept = {k: v for k, v in values.items() if k != DATA_KEY}
    new_pending = None
    if tree["pending"]:
        p = tree["pending"]
        new_pending = {"job_id": p["job_id"], "trigger": p["trigger"], "kind": p.get("kind"), "chain": ctx.chain}
    return {
        "tree": tree,
        "state": {"values": codec.encode(kept), "widget_meta": page.prev_meta, "dataset_id": dataset_id,
                  "pending": new_pending},
        "options": page.options,
    }


_DATA_URI = re.compile(r"data:([\w/+.-]+);base64,([A-Za-z0-9+/=]+)")


def externalize_assets(tree, assets: dict):
    """แทน data URI (รูป/ฟอนต์ที่หน้าเดิมฝังเป็น base64) ด้วย URL ของ asset ที่ API เสิร์ฟ — เนื้อไฟล์เดิมทุก byte"""
    def sub(m):
        mime, b64 = m.group(1), m.group(2)
        raw = base64.b64decode(b64)
        sha = hashlib.sha256(raw).hexdigest()
        assets.setdefault(sha, (mime, raw))
        return f"/api/v1/assets/{sha}"

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str) and "data:" in node:
            return _DATA_URI.sub(sub, node)
        return node

    return walk(tree)
