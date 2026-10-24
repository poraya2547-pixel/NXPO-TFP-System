# เปิดระบบให้คนอื่นดู / ใช้นำเสนอ (บน Mac เครื่องนี้)

ใช้กับการนำเสนอของจูน 29 ต.ค. 2026 และการให้เพื่อนตรวจงาน ไม่ใช่ทางขึ้นใช้งานจริง (ใช้งานจริง → `docs/IT_HANDOFF.md`)

## เปิด

```sh
cd ~/Developer/TFP_system_refactor_from_repo_20261009
sh tools/demo/start_review.sh            # Gemini จำลอง (ไม่ใช้โควตา)
sh tools/demo/start_review.sh --gemini   # Gemini จริง (คีย์ของจูนใน private/local/secrets.gemini.toml)
```

สคริปต์เปิด Docker → เปิดเว็บ (ค่าใน `private/local/env.ngrok` หรือ `env.ngrok.gemini`) → รอ health → เปิด ngrok
→ ตรวจว่าลิงก์ส่งไปหน้า login ของ Google แล้วพิมพ์ลิงก์ `https://qualify-spew-unkempt.ngrok-free.dev`

- คนที่เข้าได้: อีเมลใน `private/local/ngrok-policy.review.json` (ตอนนี้ 2 อีเมล: ดี + จูน) — **ต้องพิมพ์อีเมลเป็นตัวเล็กทั้งหมด** (Google ส่งตัวเล็ก ngrok เทียบตรงตัว)
- หน้าเตือนของ ngrok แบบฟรีให้กด Visit Site
- ระหว่างใช้: เปิด Terminal อีกหน้าต่างแล้วรัน `caffeinate -dis` · เสียบสายชาร์จ · ห้ามพับฝา (ถ้าไม่ต่อจอนอก) · เปิด Docker ไว้
- ปิด ทีมพัฒนา ได้ (ngrok รันแยก)

## ปิด

```sh
sh tools/demo/stop_review.sh
```

ปิด ngrok และคืน API/worker เป็นค่า local (รับเฉพาะ `http://127.0.0.1:8090`, Gemini จำลอง) ข้อมูลใน DB ไม่หาย

## ระหว่างนำเสนอควรรู้

- ข้อมูลเป็น snapshot ที่เก็บไว้ (ไม่ใช่ Google Sheets สด) ตัวเลขตรงกับ Streamlit ของจูนบนข้อมูลชุดเดียวกัน
- ปุ่ม "▶ เริ่มการทดสอบย้อนหลัง" ครั้งแรกต่อชุดข้อมูลรอ 35–90 วินาที (หลังจากนั้นทุกคนเห็นผลทันที) — ถ้าจะโชว์ ให้กดไว้ก่อนเริ่มนำเสนอ
- ปุ่มสรุป AI อยู่หน้าคณะวิจัย (ล็อกอินบัญชีทดสอบใน `private/local/secrets.test.toml`) — Gemini จริงใช้เวลา ~25 วินาที/ครั้ง กดครั้งเดียว
- แผนสำรอง: เปิด Streamlit เดิมของจูนไว้อีกแท็บ และมีภาพหน้าจอ/วิดีโอในสไลด์

## ซ้อมก่อนวันจริง (27–28 ต.ค.)

1. `sh tools/demo/start_review.sh` บน Mac + เน็ตที่จะใช้จริง
2. เปิดลิงก์จากเครื่องที่จะใช้นำเสนอ ล็อกอิน Google → ผู้เยี่ยมชม → ดึงข้อมูล (เมนู » บนมือถือ) → กดปุ่ม backtest → หน้าคณะวิจัย → สรุป AI → ดาวน์โหลด Word/PPTX
3. `sh tools/demo/stop_review.sh`

ตรวจสคริปต์แล้ว 21 ต.ค.: start → origin/secure cookie ถูก, gate 302 → stop → ลิงก์ 404, ค่า local คืนครบ
