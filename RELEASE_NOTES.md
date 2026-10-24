# ระบบ TFP (React + FastAPI + Postgres) — ชุดส่งมอบ

รุ่น: ต้นฉบับ `poraya2547-pixel/NXPO-TFP-System` commit `4c8aa71a2cec89208f40d13e19f75eb520b75aac` (20 ต.ค. 2026 17:15)
จัดชุด: 21 ต.ค. 2026 · สถานะ: **พร้อมใช้นำเสนอ/ทดลองภายใน** · ใช้งานจริงต้องทำรายการ "ก่อนขึ้นใช้งานจริง" ด้านล่างให้ครบ

## ข้างในมีอะไร

| ที่ | คืออะไร |
|---|---|
| `TFP.py`, `TFP_App1.3.0.py`, `data_loader.py`, รูป, `fonts/` | ต้นฉบับของเจ้าของงานที่ commit ด้านบน (ไม่แก้) — ใช้เป็นแหล่งของโค้ดคำนวณและตัวเทียบ |
| `backend/` | FastAPI + worker (โค้ดคำนวณ/หน้า/รายงาน ย้ายจากต้นฉบับด้วยตัวสร้างใน `tools/refactor/`) + tests |
| `frontend/` | หน้าเว็บ React/Vite (ติดตั้งด้วย `npm ci`) |
| `deploy/` | Docker Compose, Dockerfile, nginx, backup/restore, `.env.example` |
| `tools/` | ตัวสร้างโค้ด, เครื่องมือตรวจ parity/หน้าจอ/contrast/ความปลอดภัย, สคริปต์เปิดลิงก์ทดลอง (`tools/demo/`) |
| `docs/IT_HANDOFF.md` | วิธีติดตั้งบนเครื่องของหน่วยงาน ค่าตั้ง backup และ checklist ความปลอดภัย (หัวข้อ 7) |
| ผลตรวจความปลอดภัยระดับโค้ด | ส่งให้ IT แยก (ไม่เผยแพร่ใน repo สาธารณะ เพราะระบุจุดที่ยังต้องแก้) |
| `docs/RUNTIME_DIFFERENCES.md` | ผลที่ต่างกันระหว่าง Mac และ Linux (รอผู้รู้โมเดลรับรอง) |
| `docs/INSTALL.md` | ติดตั้งบนเครื่องตัวเอง (Windows / Mac) |
| `docs/OPERATIONS.md` | ดูแลระบบ: สเปก VM, ค่า .env จริง, HTTPS, backup, ค่าจำกัดการใช้งาน, อาการที่พบบ่อย, สิ่งที่ต้องจด |
| `docs/RUNBOOK_REVIEW.md` | เปิด/ปิดลิงก์ทดลองจาก Mac ผู้พัฒนา (ใช้นำเสนอ) |
| `docs/baseline/`, `docs/contracts/` | ชุดอ้างอิง (hash/เงื่อนไข ไม่มีค่าข้อมูล) และสัญญา API |
| `MANIFEST.sha256` | hash ทุกไฟล์ในชุดนี้ |

**ไม่ได้ใส่ (ตั้งใจ):** ข้อมูลจริง/snapshot ของชีต ผลทดสอบเต็ม ค่าลับทุกชนิด (service account, Gemini key, รหัสคณะวิจัย) — เจ้าของงานส่งค่าลับให้ผู้ติดตั้งทางช่องทางลับเอง
test ที่เทียบตัวเลขต้องใช้ snapshot `private/baseline/sheets_raw.json` และผล oracle ใน `private/` ซึ่งอยู่กับผู้พัฒนา

## เปลี่ยนจากต้นฉบับ Streamlit อย่างไร

- หน้าเว็บ React อ่านผลที่ worker คำนวณไว้ใน Postgres (ไม่คำนวณซ้ำทุกครั้งที่เปิดหน้า) — ตัวเลขและหน้าจอเท่าต้นฉบับ
- การทดสอบย้อนหลัง (Rolling/Hold-out) คำนวณเมื่อกดปุ่ม "▶ เริ่มการทดสอบย้อนหลัง" แล้วเก็บใน DB ใช้ร่วมทุกคน (แทนไฟล์ `backtest_cache.pkl` ของต้นฉบับ)
- เว็บล็อกธีมสว่างเสมอ (ต้นฉบับในโหมดมืดอ่านไม่ออก)
- เพิ่ม: session/CSRF/จำกัดการลองรหัส, security headers, งานหนักแยก worker, backup/restore

## ผลตรวจ (บนเครื่องผู้พัฒนา 20–21 ต.ค. 2026)

- ตัวเลข: 36 ผลตรงต้นฉบับทุกบิตบน runtime เดียวกัน (Mac และ Linux arm64) · หน้าจอ 53 สถานะตรงทุก element
- backtest ตรงไฟล์ cache ของเจ้าของงานทุกค่า (MAPE ARIMA/Naive/Drift 2.459/2.661/2.193, 60 จุด)
- test backend 102/102 (Mac และ Linux), API/DB/worker 44/44, e2e ระบบเต็ม (restart, worker ล่มกลางงาน) ผ่าน
- contrast ทุกหน้า 0 ข้อผิด · ยิงทดสอบความปลอดภัย 74 ข้อ ไม่ผ่าน 0
- Gemini จริง 1 ครั้ง: บทสรุป + Word/PPTX ใช้ได้ ตัวเลขปีต่อปีตรงแดชบอร์ด (252.60 → 256.69, +1.62%)

## รันทดลองบนเครื่องตัวเอง

```sh
cp deploy/.env.example deploy/.env   # ใส่ค่าในไฟล์ (ห้ามส่งไฟล์นี้ออกทางแชต)
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
# เปิด http://127.0.0.1:<TFP_WEB_PORT>
```

ต้องมีไฟล์ค่าลับรูปแบบ `secrets.toml` เดิม (`TFP_SECRETS_PATH`) จึงจะดึง Google Sheets/ใช้ Gemini จริงได้

## ก่อนขึ้นใช้งานจริง (ดู `docs/IT_HANDOFF.md` หัวข้อ 6.1 และ 7)

1. VM ของหน่วยงาน + HTTPS + จำกัดเครือข่ายสำนักงาน/VPN
2. ตั้ง real IP หลัง proxy (นับการล็อกอินผิดแยกคน) และ hardening container
3. ต่อ Google Sheets/Gemini จริงด้วยค่าลับของหน่วยงาน, กำหนดผู้ดูแลบัญชี/backup
4. ผู้รู้โมเดลรับรองความต่าง Mac/Linux (4 ผล) และ load test + pentest โดยผู้ตรวจภายนอก

## ข้อสังเกตในต้นฉบับ (ไม่ได้แก้ — ให้เจ้าของงานตัดสิน)

- รายงาน Word: หมายเหตุใต้ตารางแสดง "*, , *" แทน "***, **, *" (ตัวแปลง `**` เป็นตัวหนา)
- กราฟในรายงาน Word: ป้ายปี 2021 และ 2022 ซ้อนกัน
