# คู่มือดูแลระบบ (สำหรับ IT / ผู้ดูแลต่อ)

อ่านคู่กับ `docs/IT_HANDOFF.md` (โครงระบบ ค่าตั้ง backup checklist ความปลอดภัย) และ `docs/INSTALL.md` (รันบนเครื่องตัวเอง)
ตัวเลขในหน้านี้วัดบนเครื่องผู้พัฒนา (Docker บน Mac M3, Linux arm64) 21–24 ต.ค. 2026 ด้วยข้อมูล snapshot ไม่ใช่ผลบน VM ของหน่วยงาน

## 1. สเปก VM

| | ที่วัดได้ | แนะนำ |
|---|---|---|
| หน่วยความจำ | api ~410–600 MB, worker ~220–450 MB (สูงสุดตอน backtest 222 MB), db ~60 MB, web ~17 MB → รวมราว 1–1.2 GB | **4 GB** (2 GB ตึงเกินไป) |
| CPU | งานหนักสุดคือ Rolling backtest ใช้ 1 core ราว 35–60 วินาทีต่อชุดข้อมูล (ครั้งแรกเท่านั้น) worker ทำทีละงาน | **2 vCPU** |
| ดิสก์ | image backend 1.4 GB, postgres 0.4 GB, web 0.1 GB; ฐานข้อมูล ~20 MB (โตตามจำนวนครั้งที่ดึงข้อมูล/รายงาน) | **40 GB** (เผื่อ build cache ถ้า build บน VM และไฟล์ backup) |
| เครือข่าย | worker ต้องออกอินเทอร์เน็ตไป Google Sheets/Gemini; api/db ไม่ต้อง | เปิดเข้าเฉพาะ 443 จากเครือข่ายสำนักงาน/VPN |

VM แบบ x86-64 (amd64) ให้ผล backtest/p-value บางค่าต่างจาก Mac ในทศนิยมท้าย ๆ (`docs/RUNTIME_DIFFERENCES.md`) — ให้ผู้รู้โมเดลรับรองก่อนใช้จริง

## 2. ค่า `deploy/.env` สำหรับเว็บจริง

| ค่า | ตั้งเป็น |
|---|---|
| `TFP_DB_PASSWORD` | สุ่มยาว ≥ 32 ตัว (IT ตั้งเอง เก็บในที่เก็บค่าลับของหน่วยงาน) |
| `TFP_ALLOWED_ORIGINS` | URL ที่ผู้ใช้เปิดจริงเท่านั้น เช่น `https://tfp.<โดเมน>` (ห้ามมี localhost) |
| `TFP_COOKIE_SECURE` | `1` |
| `TFP_SECRETS_PATH` | path ของ `secrets.toml` บน VM (สิทธิ์ 600 เจ้าของคือผู้ดูแล) |
| `TFP_WEB_BIND` / `TFP_WEB_PORT` | `127.0.0.1` / `8080` (ให้ HTTPS proxy บนเครื่องเดียวกันต่อเข้ามา) |
| `TFP_SESSION_IDLE_MINUTES` / `TFP_SESSION_MAX_HOURS` | ค่าเริ่ม 240 / 24 — ยืนยันกับเจ้าของงาน |
| `TFP_SHEETS_FIXTURE`, `TFP_GEMINI_FIXTURE` และ `*_MOUNT` | **ห้ามตั้ง** (เป็นโหมดทดสอบ) |
| `TFP_VERSION` | ชื่อรุ่นของ image (เช่น วันที่หรือ commit) ใช้ย้อนกลับได้ |

ตรวจหลังเปิด: `docker compose ... exec api printenv TFP_COOKIE_SECURE TFP_ALLOWED_ORIGINS` และ worker ต้องไม่มี `TFP_SHEETS_FIXTURE`/`TFP_GEMINI_FIXTURE`

## 3. HTTPS

**compose ไม่มีตัวจัดการ HTTPS** — container `web` (nginx) ให้บริการ HTTP ที่ `127.0.0.1:8080` เท่านั้น IT ต้องวาง reverse proxy ของหน่วยงาน (nginx/Caddy/load balancer) ไว้หน้าเครื่อง:

- ถือใบรับรอง TLS ของโดเมน, ตั้ง HSTS, ส่งต่อไป `http://127.0.0.1:8080`
- ส่ง IP จริงของผู้ใช้ และแก้ `deploy/web.conf` ให้เชื่อ IP จาก proxy นั้นเท่านั้น (`set_real_ip_from <IP proxy>` + `real_ip_header X-Forwarded-For`) — ไม่งั้นการนับล็อกอินผิด 5 ครั้งจะนับรวมทุกคน
- จำกัดจำนวนคำขอต่อ IP ที่ proxy (ระบบจำกัดต่อ session เท่านั้น)

ตัวอย่าง nginx ด้านหน้า (ยังไม่ได้ทดสอบบน VM ของหน่วยงาน):

```nginx
server {
    listen 443 ssl;
    server_name tfp.example.go.th;
    ssl_certificate     /etc/ssl/tfp/fullchain.pem;
    ssl_certificate_key /etc/ssl/tfp/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}
```

## 4. สำรองและกู้คืนฐานข้อมูล

```sh
# สำรอง (ไฟล์ใหม่ทุกครั้ง ไม่เขียนทับ สิทธิ์ไฟล์จำกัด) — ชื่อ container ดูจาก docker compose ps
sh deploy/backup.sh tfp-db-1 /secure-backups/tfp-$(date +%Y%m%d-%H%M).dump
# กู้คืนเข้า DB ใหม่ชื่อขึ้นต้น tfp_restore_ เพื่อตรวจ (ไม่ทับฐานจริงอัตโนมัติ)
sh deploy/restore.sh <container ของ Postgres ที่ใช้ทดสอบ> tfp_restore_check /secure-backups/tfp-YYYYMMDD-HHMM.dump
```

- ตั้ง cron สำรองอย่างน้อยวันละครั้ง คัดลอกไปเก็บนอกเครื่องแบบเข้ารหัส และทดลองกู้คืนเดือนละครั้ง
- ในฐานข้อมูลมี: ข้อมูลที่ดึงจากชีต, ประวัติการดึง, ผลคำนวณ (คำนวณใหม่ได้), session, ไฟล์รายงาน, บันทึกการปรับตัวแปร
- ห้ามใช้ `docker compose down -v` กับระบบจริง (ลบ volume ของฐานข้อมูล)
- ก่อนอัปเดตรุ่น: สำรองก่อนทุกครั้ง และเก็บ image รุ่นเดิม (`docker image tag tfp-backend:<เดิม> tfp-backend:before-<วันที่>`)

## 5. ค่าจำกัดการใช้งานที่มีในระบบ

| เรื่อง | ค่าเริ่มต้น | หมายเหตุ |
|---|---|---|
| ปุ่มสรุปด้วย AI (Gemini) | เฉพาะหน้าคณะวิจัย | ผู้เยี่ยมชมเรียกไม่ได้ (ทดสอบแล้ว: API ตอบ 400) · กดซ้ำเรียก Gemini ใหม่ทุกครั้งตามต้นฉบับ ไม่มีเพดานต่อวัน |
| ดึงข้อมูลต่อ session | 20 ครั้ง/ชั่วโมง | |
| คำขอต่อ session | 120 ครั้ง/นาที | |
| งานดึงข้อมูลที่รอพร้อมกันทั้งระบบ | 30 | |
| ล็อกอินผิด | 5 ครั้ง/15 นาที ต่อ session และต่อ IP | ต้องตั้ง real IP ตามหัวข้อ 3 |
| ขนาดคำขอ | 64 KB | |

ค่าเหล่านี้ตั้งผ่าน env `TFP_FETCH_PER_HOUR`, `TFP_EVENTS_PER_MINUTE`, `TFP_MAX_PENDING_FETCH`, `TFP_LOGIN_MAX_FAILURES`, `TFP_LOGIN_WINDOW_MINUTES`
แต่ **`deploy/compose.yaml` ยังไม่ส่งค่าเหล่านี้เข้า container** — ถ้าจะปรับ ต้องเพิ่มใน `environment` ของ api/worker ก่อน
Session ใหม่สร้างได้ไม่จำกัด จึงควรจำกัดต่อ IP ที่ proxy และพิจารณาใช้ API key ของหน่วยงานที่ตั้งงบ/เพดานใน Google Cloud

## 6. ใช้งานพร้อมกันหลายคน (ทดสอบ 24 ต.ค. บนเครื่องผู้พัฒนา)

- ผู้เยี่ยมชม 10 คนกดดึงข้อมูลพร้อมกัน: สำเร็จ 10/10 เสร็จใน 2.8 วินาที
- 10 คนกดปุ่มทดสอบย้อนหลังพร้อมกันครั้งแรก: สร้างงานคำนวณ **1 งาน** ใช้ร่วมกัน ทุกคนได้ผลใน ~59 วินาที
- คนที่เข้ามาทีหลังเห็นผลทันที ไม่มีปุ่มให้กด ไม่สร้างงานใหม่
- worker ทำทีละงาน: ระหว่างคำนวณ backtest ครั้งแรก งานอื่น (ดึงข้อมูล/สรุป AI) จะรอคิว — ยังไม่ได้ทำ load test บน VM จริง

ผล backtest เก็บในฐานข้อมูลต่อชุดข้อมูล (เนื้อหาชีตเดิม = ชุดเดิม) ใช้ร่วมทุก session และอยู่รอดการรีสตาร์ต
ต้องคำนวณใหม่เมื่อ: ข้อมูลในชีตเปลี่ยน หรือ อัปเดตโค้ดคำนวณ/runtime รุ่นใหม่

## 7. ตรวจสุขภาพและอาการที่พบบ่อย

- `GET /api/v1/health` → `{"status": "ok"|"degraded", "database": …, "worker_seen_seconds_ago": …}` ให้ระบบเฝ้าระวังอ่าน `status` (HTTP 200 อย่างเดียวไม่พอ)
- log: `docker compose -f deploy/compose.yaml --env-file deploy/.env logs --tail=200 api worker web`
- หน้าเว็บที่ error จะแสดงรหัส `ref` — ค้นใน log ด้วย `page run failed ref=<รหัส>`

| อาการ | สาเหตุที่พบบ่อย / แก้ |
|---|---|
| health `degraded`, `worker_seen_seconds_ago` สูง | worker หยุด → `docker compose ... restart worker` (งานคำนวณที่ค้างจะทำซ้ำเอง งานดึงข้อมูลที่ค้างจะล้มเหลวให้กดใหม่) |
| ดึงข้อมูลไม่สำเร็จ | สิทธิ์ service account ต่อชีต, ชีตเปลี่ยนรูปแบบ, หรือ Google ตอบช้า (timeout 60 วินาที) — ข้อความ error แสดงที่แถบดึงข้อมูล |
| สรุป AI ขึ้นข้อความโควตา | โควตา Gemini ของคีย์หมด รอรอบวันใหม่ หรือใช้คีย์ของหน่วยงานที่มีงบ |
| ปุ่มทดสอบย้อนหลังรอนาน | ปกติ 35–90 วินาทีครั้งแรกต่อชุดข้อมูล |
| กดแล้ว 403 | URL ไม่ตรง `TFP_ALLOWED_ORIGINS` หรือ cookie Secure บน http |
| ทุกคนล็อกอินไม่ได้ 15 นาที | มีคนกรอกรหัสผิด 5 ครั้งจาก IP เดียวกัน (ดูหัวข้อ 3 เรื่อง real IP) |
| ดิสก์เต็ม | ล้าง image/build cache เก่า (`docker image prune`, `docker builder prune`) และไฟล์ backup เก่า — ห้ามลบ volume ฐานข้อมูล |

## 8. อัปเดตเมื่อเจ้าของงานแก้โค้ดต้นฉบับ (TFP.py / TFP_App1.3.0.py)

โค้ดคำนวณและหน้าเว็บของระบบใหม่สร้างจากไฟล์ต้นฉบับด้วย `tools/refactor/extract_core.py`, `extract_page.py`, `extract_reports.py` — **ห้ามแก้ไฟล์ที่สร้างด้วยมือ**
ขั้นตอนต่อรุ่น: ตรึง commit ต้นฉบับ → รัน oracle ของต้นฉบับ (`tools/baseline/oracle.py`) และเก็บหน้าจอ (`ui_capture.py`) บน runtime เดียวกับระบบ
→ ตรึงชุดอ้างอิง (`freeze_baseline.py`) → สร้างโค้ดใหม่ด้วยตัวสร้าง → รัน `backend/tests`, `backend/tests_api` → build image → สำรอง DB → อัปเดต
ขั้นตอนนี้ต้องใช้ snapshot ของชีต (`private/baseline/sheets_raw.json`) ซึ่งไม่อยู่ใน repo — ขอจากเจ้าของงาน

## 9. สิ่งที่ควรจดทุกครั้ง

**ทุกครั้งที่ติดตั้ง/อัปเดต:** วันที่, commit ของ repo, commit ต้นฉบับที่ใช้, image ID ของ backend/web, ค่า `.env` ที่เปลี่ยน (ไม่จดค่าลับ), ไฟล์ backup ก่อนอัปเดต, ผล test, ผู้ทำ
**ทุกครั้งที่มีปัญหา:** เวลา, อาการ/หน้าที่เจอ, รหัส `ref` บนหน้า, ผล `/api/v1/health`, log ที่เกี่ยวข้อง (ตัดค่าลับออก), สาเหตุ, วิธีแก้, ต้องแจ้งผู้ใช้หรือไม่
**ข้อมูลถาวร:** ผู้ดูแล VM/backup, ผู้ดูแลบัญชีคณะวิจัยและ service account, เจ้าของ Gemini key/งบ, ผู้รู้โมเดล (รับรองตัวเลข), วันหมดอายุใบรับรอง HTTPS,
กำหนดเปลี่ยนรหัสคณะวิจัย (เช่น เมื่อมีคนออกจากทีม), ประวัติทดลองกู้คืน backup
