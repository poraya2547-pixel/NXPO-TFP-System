-- ตารางเริ่มต้นของระบบ TFP (Postgres 17) — ใช้ผ่าน app/db.py migrate() ตามลำดับเลขไฟล์ ห้ามแก้ไฟล์ที่ใช้ไปแล้ว
-- session ฝั่ง server (แทน session_state ของ Streamlit), ข้อมูลชีตที่ดึง, ผลคำนวณที่ worker เตรียม, คิวงาน,
-- บันทึกการดึงข้อมูล (เดิมไฟล์ fetch_log.csv), ไฟล์ดาวน์โหลดของแต่ละ session, การล็อกอินผิด และ audit

CREATE TABLE sessions (
    id          uuid PRIMARY KEY,
    token_hash  text NOT NULL UNIQUE,          -- sha256 ของ token ใน cookie (ไม่เก็บ token ดิบ)
    csrf_token  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,          -- หมดอายุแบบนับจากสร้าง (absolute)
    state       jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX sessions_expires_at ON sessions (expires_at);

CREATE TABLE datasets (
    id              bigserial PRIMARY KEY,
    content_sha256  text NOT NULL UNIQUE,      -- เนื้อหาเดิมไม่สร้างซ้ำ (dataset แก้ไม่ได้)
    data            jsonb NOT NULL,            -- DataFrame จาก loader เดิม (app/codec.py)
    source          jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE results (
    id                   bigserial PRIMARY KEY,
    dataset_id           bigint NOT NULL REFERENCES datasets(id),
    kind                 text NOT NULL CHECK (kind IN ('ecm', 'series')),
    options_key          text NOT NULL,        -- ชุดตัวแปร (ecm) หรือ '' (series)
    code_version         text NOT NULL,
    runtime_fingerprint  text NOT NULL,
    payload              jsonb NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, kind, options_key, code_version, runtime_fingerprint)
);

CREATE TABLE jobs (
    id            uuid PRIMARY KEY,
    session_id    uuid,                        -- ผู้สร้าง (งานคำนวณที่ input เดียวกันใช้ร่วมกันได้ตาม dedupe_key)
    kind          text NOT NULL,
    params        jsonb NOT NULL,
    dedupe_key    text,
    status        text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    result        jsonb,
    error         jsonb,
    attempts      int NOT NULL DEFAULT 0,
    max_attempts  int NOT NULL DEFAULT 3,
    run_after     timestamptz NOT NULL DEFAULT now(),
    claimed_by    text,
    claim_token   uuid,
    lease_until   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    started_at    timestamptz,
    finished_at   timestamptz
);
CREATE UNIQUE INDEX jobs_active_dedupe ON jobs (dedupe_key) WHERE status IN ('queued', 'running');
CREATE INDEX jobs_queue ON jobs (status, run_after, created_at);

CREATE TABLE fetch_log (
    id         bigserial PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    timestamp  text NOT NULL,                  -- ข้อความเวลาแบบเดิม เช่น "27 กันยายน 2569 เวลา 23:50 น."
    "user"     text NOT NULL                   -- "คณะวิจัย" หรือ "ผู้เยี่ยมชม"
);

CREATE TABLE downloads (
    ref         text PRIMARY KEY,              -- รหัสสุ่ม ใช้ใน URL ดาวน์โหลด
    session_id  uuid NOT NULL,
    sha256      text NOT NULL,
    file_name   text NOT NULL,
    mime        text NOT NULL,
    data        bytea NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, sha256, file_name, mime)
);

CREATE TABLE login_failures (
    id      bigserial PRIMARY KEY,
    key     text NOT NULL,                     -- "s:<session id>" หรือ "ip:<ที่อยู่>"
    at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_failures_key_at ON login_failures (key, at);

CREATE TABLE audit (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    event       text NOT NULL,                 -- login_ok, login_failed, logout, fetch_requested, job_failed, download
    session_ref text,                          -- 8 ตัวแรกของ session id (ไม่ใช่ token)
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE workers (
    name     text PRIMARY KEY,                 -- ชื่อ process ของ worker
    seen_at  timestamptz NOT NULL DEFAULT now()
);
