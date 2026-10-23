# สัญญาข้อมูลของ API (Step 3)

ฐาน: `/api/v1` · JSON UTF-8 · สัญญาเต็มอยู่ที่ `openapi.json` (สร้างด้วย `tools/refactor/export_openapi.py` จาก `backend/app/main.py` + `schemas.py` ห้ามแก้ด้วยมือ)
หน้าเว็บใช้ types ที่สร้างจากไฟล์นี้ (`frontend/src/api/schema.d.ts` ด้วย `npm run gen:api`); `npm run check:api` ตรวจว่าไม่ล้าสมัย และถูกเรียกทุกครั้งที่ build image ของเว็บ

## 1. แนวคิด

หน้าเว็บไม่มี endpoint ต่อ helper function: backend รันโค้ดหน้าเดิม (`backend/app/page_script.py`) ต่อคำขอด้วย `st` ตัวแทน แล้วส่ง
**element tree** — หนึ่ง element ต่อหนึ่งคำสั่ง `st.*` ของหน้าเดิม ตามลำดับเดิม — ให้ React แสดง การกระทำของผู้ใช้ (กดปุ่ม/เปลี่ยนค่า) ส่งกลับเป็น event
แล้วได้ tree ใหม่ทั้งหน้า (เหมือน Streamlit rerun) การคำนวณหนักและงานภายนอกทำใน worker เป็น job (ดู `pending`)

## 2. Endpoints

| Method / path | ใครเรียกได้ | Request | Response | Error |
|---|---|---|---|---|
| `GET /api/v1/view` | ทุกคน (ไม่มี cookie จะสร้าง session ใหม่และตั้ง cookie) | — | `View` | 503/500 |
| `POST /api/v1/events` | เจ้าของ session; ต้องมี `Origin` อยู่ใน `TFP_ALLOWED_ORIGINS` และ header `X-CSRF-Token` ตรงกับ session | `Event` | `View` (cookie ใหม่เมื่อเข้าสู่ระบบ/ออกจากระบบ) | 400 event ไม่ถูกต้อง · 403 origin/CSRF · 413 ใหญ่เกิน/ไม่ระบุขนาด · 429 ถี่เกิน/ลองรหัสผ่านเกิน |
| `GET /api/v1/pending` | เจ้าของ session | — | `PendingStatus` (`queued`/`running`/`succeeded`/`failed`) | — |
| `GET /api/v1/downloads/{ref}` | **เฉพาะ session ที่สร้างไฟล์** | — | ไฟล์ (`Content-Disposition` ชื่อ UTF-8) | 404 ถ้าไม่ใช่เจ้าของ/ไม่มี |
| `GET /api/v1/assets/{sha256}` | ทุกคน | — | รูป/ฟอนต์ที่หน้าเดิมฝังเป็น base64 (เนื้อไฟล์เดิม, cache immutable) | 404 |
| `GET /api/v1/health` | ทุกคน (ใช้ตรวจระบบ) | — | `Health`: `ok` เมื่อ DB ต่อได้และ worker รายงานภายใน 120 วินาที ไม่งั้น `degraded` | 503 เมื่อ DB ต่อไม่ได้ |

ไม่มี `/docs` หรือ `/redoc` (ปิดไว้); เอกสารเครื่องอ่านได้ที่ `GET /api/v1/openapi.json`

## 3. Session และสิทธิ์

- cookie `tfp_session`: HttpOnly, SameSite=Lax, host-only, path `/`, Secure ตาม `TFP_COOKIE_SECURE` (ค่าเริ่มต้นเปิด; ปิดได้เฉพาะเครื่องพัฒนาแบบ http)
- token สุ่ม 256 บิต เก็บเฉพาะ hash ใน Postgres; หมดอายุเมื่อไม่ใช้ `TFP_SESSION_IDLE_MINUTES` (240) หรือครบ `TFP_SESSION_MAX_HOURS` (24)
- เปลี่ยน token เมื่อสถานะเข้าสู่ระบบเปลี่ยน (เข้าสู่ระบบสำเร็จ/ออกจากระบบ) และบันทึก audit
- **สิทธิ์ของแต่ละหน้า/ปุ่มตัดสินโดยโค้ดหน้าเดิมฝั่ง server** (ค่า `research_authenticated` อยู่ใน session ฝั่ง server ผู้ใช้แก้ไม่ได้)
  API ไม่มี endpoint อ่านผลโมเดลตรง ผลทุกอย่างผ่านหน้าเดิมเท่านั้น
- จำกัด: event ต่อนาที `TFP_EVENTS_PER_MINUTE` (120) · การดึงข้อมูลต่อชั่วโมงต่อ session `TFP_FETCH_PER_HOUR` (20) และงานดึงข้อมูลที่รอ/กำลังทำทั้งระบบ
  `TFP_MAX_PENDING_FETCH` (30) แสดงในแถบข้อความเดิมของหน้าโดยไม่สร้างงาน · timeout ต่อคำขอ Google Sheets ของงานดึง `TFP_SHEETS_TIMEOUT_SECONDS` (60) ·
  ลองรหัสผ่านผิด `TFP_LOGIN_MAX_FAILURES` (5) ครั้งใน `TFP_LOGIN_WINDOW_MINUTES` (15) นาที นับแยกต่อ session และต่อที่อยู่ IP · ขนาดคำขอ `TFP_MAX_BODY_BYTES` (65536)
- เวลา "ดึงข้อมูลล่าสุดเมื่อ" และประวัติการดึง = เวลาที่ worker อ่านชีตสำเร็จ (ผลของงานดึงมี `read_at`) เหมือนหน้าเดิมที่บันทึกทันทีหลังอ่าน
- ช่องรหัสผ่านไม่ถูกเก็บใน session และไม่ส่งกลับไปที่หน้า

## 4. `View` และ element tree

```
View = { main: Root, sidebar: Root, page_config: {page_title, layout, ...}, pending: bool, csrf_token: str }
Root = { type: "main" | "sidebar", children: Element[] }
```

| type | สร้างจาก | ฟิลด์สำคัญ |
|---|---|---|
| `markdown` | `st.markdown`, `st.caption` (`kind`), `st.write(str)` | `body` (ข้อความหลัง `clean_text` แบบ Streamlit), `allow_html` |
| `alert` | `st.info/success/warning/error` | `kind`, `body`, `icon` (emoji นำหน้าที่ Streamlit แยกออกมา) |
| `button` | `st.button`, `st.form_submit_button` (`is_form_submitter`, `form_id`) | `id`, `label`, `kind` (primary/secondary/tertiary), `icon`, `disabled` |
| `download_button` | `st.download_button` | `id`, `ref`, `url` (`/api/v1/downloads/<ref>`), `file_name`, `mime` |
| `selectbox` | `st.selectbox` | `options` (ข้อความหลัง format_func), `index` (int หรือ null) |
| `multiselect` | `st.multiselect` | `options`, `value` (ลำดับ index) |
| `number_input`, `slider` | `st.number_input`, `st.slider` | `value`, `min`, `max`, `step`, `format`, `int` |
| `toggle` | `st.toggle` | `value` |
| `text_input`, `text_area` | `st.text_input`, `st.text_area` | `value` (ช่อง password เป็น `""` เสมอ), `input_type`, `max_chars` |
| `vega_lite_chart` | `st.altair_chart` | `spec` = `chart.to_dict()` แบบ Streamlit 1.64 (ธีม Altair ปิดระหว่าง to_dict, autosize fit/padding, ชื่อ legend null → " ") |
| `dataframe` | `st.dataframe` | `columns`, `index`, `rows` |
| `spinner` | `st.spinner` ระหว่างรอ job | `text` |
| `exception` | exception ในโค้ดหน้า | `ref` (รหัสอ้างอิงใน log) |
| `container`, `columns`/`column`, `expander`, `form` | กล่องจัดหน้า | `children` (และ `key`, `border`, `weight`, `gap`, `vertical_alignment`, `expanded`) |

**id ของ widget:** key ที่ผู้เขียนตั้ง; ไม่ตั้ง key = `$$auto-<ชนิด>-<hash ของ label/พารามิเตอร์>`; ปุ่ม submit ที่ไม่ตั้ง key = `FormSubmitter:<form>-<label>` (กติกาเดียวกับ Streamlit 1.64)

## 5. `Event`

```
Event = { trigger?: str (≤ 400 ตัวอักษร), values: { <id>: bool | int | float | str | int[] | null }, resume: bool }
```

- `values` คือค่าใหม่ของ widget ที่ผู้ใช้เปลี่ยน — selectbox ส่ง index, multiselect ส่ง list ของ index, toggle ส่ง bool, ช่องตัวเลขส่งตัวเลข, ช่องข้อความส่ง str
- ค่าถูกตรวจกับ metadata ของรอบก่อน (ชนิด, ช่วง min/max, จำนวนเต็ม, index อยู่ในช่วง, ไม่ซ้ำ, ความยาว) ไม่ผ่านตอบ 400 ไม่รันหน้า
- `trigger` คือ id ของปุ่มที่กด (ต้องมีอยู่ในหน้ารอบก่อน ไม่งั้น 400 "ไม่พบปุ่มที่อ้างถึง"); id ใน `values` ต้องมีอยู่ในหน้ารอบก่อนเช่นกัน
- ช่องในฟอร์มส่งได้พร้อมปุ่ม submit ของฟอร์มนั้นเท่านั้น (ปุ่ม submit ส่งค่าทุกช่องของฟอร์มพร้อมกัน; Enter ในช่องข้อความของฟอร์ม = กด submit ปุ่มแรก)
- `resume: true` รันหน้าต่อหลัง job ที่รอเสร็จ (หน้าเว็บถาม `/pending` ทุก 1 วินาทีระหว่าง `View.pending`)

## 6. ตัวเลข หน่วย และค่าว่าง

- ตัวเลขที่ผู้ใช้เห็นส่วนใหญ่อยู่ใน `markdown.body` เป็นข้อความที่โค้ดหน้าเดิม format แล้ว — API ไม่ปัดหรือแปลงหน่วยซ้ำ
- กราฟส่งค่าดิบใน `spec` ตามที่ Altair สร้าง (Streamlit ส่ง spec เดียวกันด้วย `json.dumps`) ค่า NaN ใน dataset Altair เปลี่ยนเป็น null เหมือนเดิม
- `dataframe.rows`: ตัวเลขที่ finite ส่งเป็นตัวเลข JSON; NaN, ±inf, None, `pd.NA`, `NaT` ส่งเป็น `null` (แสดง "None"); ชนิดอื่นแปลงเป็นข้อความ — หน้าเดิมใช้ `st.dataframe` ที่เดียว (บันทึกการใช้งานในหน้าคณะวิจัย เป็นข้อความ)
- response ไม่มี NaN/Infinity ใน JSON (FastAPI ปฏิเสธ ไม่แทนเป็นตัวเลขอื่นแบบเงียบ)

## 7. Error

- 4xx: `{"detail": "<ข้อความภาษาไทย>"}`
- 500: `{"detail": "เกิดข้อผิดพลาดในระบบ", "ref": "<12 hex>"}` — traceback อยู่ใน log ของ api พร้อม ref เดียวกัน ไม่ส่งให้ผู้ใช้
- exception ในโค้ดหน้าเดิมแสดงเป็น element `exception` ที่มีเฉพาะ ref (Streamlit เดิมแสดง traceback บนหน้า — ต่างโดยตั้งใจตามแผน §20.3)
- ข้อความ error จากภายนอก (เช่นตอนดึงชีตจากลิงก์ที่ผู้ใช้กรอก) ถูก escape ก่อนแทรกลง HTML
