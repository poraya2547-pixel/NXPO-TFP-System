"""ที่เก็บในหน่วยความจำ สำหรับ test และตรวจหน้าจอเทียบหลักฐานเดิม (ไม่มี Postgres/worker)

job ทำทันทีใน process ตอนสร้าง (ผลเหมือน worker เพราะเรียก jobs.execute ตัวเดียวกัน) ข้อมูลเก็บผ่าน codec
เหมือนใน Postgres เพื่อให้หน้าได้วัตถุที่ถอดกลับแบบเดียวกับระบบจริง
"""
import hashlib
import json
import uuid

from . import codec, compute, jobs


def _key(lr_vars, sr_spec) -> str:
    return json.dumps([list(lr_vars), [list(s) for s in sr_spec]], ensure_ascii=False)


class MemoryStore:
    def __init__(self, fetch_log=None):
        self._datasets, self._by_hash, self._ecm, self._series = {}, {}, {}, {}
        self._jobs, self._downloads = {}, {}
        self._fetch_log = list(fetch_log or [])

    # ----- dataset / ผลคำนวณ -----
    def add_dataset(self, raw, source=None) -> int:
        enc = json.dumps(codec.encode(raw), sort_keys=True)
        h = hashlib.sha256(enc.encode()).hexdigest()
        if h not in self._by_hash:
            self._by_hash[h] = len(self._datasets) + 1
            self._datasets[self._by_hash[h]] = enc
        return self._by_hash[h]

    def dataset(self, dataset_id):
        return codec.decode(json.loads(self._datasets[dataset_id]))

    def ecm(self, dataset_id, lr_vars, sr_spec):
        enc = self._ecm.get((dataset_id, _key(lr_vars, sr_spec)))
        return None if enc is None else compute.unpack(json.loads(enc))

    def save_ecm(self, dataset_id, lr_vars, sr_spec, bundle):
        self._ecm[(dataset_id, _key(lr_vars, sr_spec))] = json.dumps(compute.pack(bundle))

    def series(self, dataset_id):
        enc = self._series.get(dataset_id)
        return None if enc is None else compute.unpack(json.loads(enc))

    def save_series(self, dataset_id, bundle):
        self._series[dataset_id] = json.dumps(compute.pack(bundle))

    # ----- job (ทำทันที) -----
    def start_job(self, session_id, kind, params) -> str:
        job_id = uuid.uuid4().hex
        try:
            self._jobs[job_id] = {"status": "succeeded", "result": jobs.execute(self, kind, params), "error": None}
        except Exception as e:
            self._jobs[job_id] = {"status": "failed", "result": None, "error": compute.error_record(e)}
        self._jobs[job_id].update(session_id=session_id, kind=kind)
        return job_id

    def job(self, job_id):
        return self._jobs[job_id]

    def count_jobs(self, session_id, kind, minutes):
        return sum(1 for j in self._jobs.values() if j.get("session_id") == session_id and j.get("kind") == kind)

    def count_pending(self, kind):
        return sum(1 for j in self._jobs.values() if j.get("kind") == kind and j["status"] in ("queued", "running"))

    # ----- บันทึกการดึงข้อมูล / ไฟล์ดาวน์โหลด -----
    def fetch_log_append(self, row: dict):
        self._fetch_log.append({"timestamp": row["timestamp"], "user": row["user"]})

    def fetch_log_rows(self):
        return [dict(r) for r in self._fetch_log[-1000:]]

    def put_download(self, session_id, data: bytes, file_name: str, mime: str) -> str:
        ref = hashlib.sha256(data).hexdigest()
        self._downloads[(session_id, ref)] = (data, file_name, mime)
        return ref

    def _downloads_by_ref(self):
        return {ref: v for (_, ref), v in self._downloads.items()}
