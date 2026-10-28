# ติดตั้งบนเครื่องตัวเอง (Windows / Mac)

สำหรับลองใช้หรือพัฒนาบนเครื่องตัวเอง — ขึ้นเซิร์ฟเวอร์ให้คนอื่นใช้ ดู `docs/OPERATIONS.md` และ `docs/IT_HANDOFF.md`

## 1. ลงโปรแกรม (ครั้งเดียว)

- Docker Desktop (Windows: เปิด WSL 2 ตามที่ตัวติดตั้งถาม แล้วรีสตาร์ต) เปิดทิ้งไว้จนขึ้น Engine running
- Git

## 2. ดึงโค้ด

```sh
git clone -b refactor-react-fastapi https://github.com/poraya2547-pixel/NXPO-TFP-System.git
cd NXPO-TFP-System
```

(หลัง merge เข้า main แล้ว ไม่ต้องใส่ `-b refactor-react-fastapi`)
Windows: repo มี `.gitattributes` บังคับไฟล์ของระบบเว็บเป็นบรรทัดแบบ LF แล้ว — ถ้า clone ไว้ก่อน 24 ต.ค. 2026 ให้ clone ใหม่ (ไม่งั้น build หน้าเว็บจะล้มที่ `check:api`)

## 3. ไฟล์ตั้งค่า

```sh
cp deploy/.env.example deploy/.env          # Windows PowerShell: copy deploy\.env.example deploy\.env
```

แก้ `deploy/.env`:

```
TFP_DB_PASSWORD=<ตั้งเองยาว ๆ สุ่ม>
TFP_ALLOWED_ORIGINS=http://localhost:8080
TFP_COOKIE_SECURE=0
TFP_SECRETS_PATH=<ที่อยู่เต็มของ secrets.toml ตัวเดียวกับที่ใช้รัน Streamlit>   # Windows ใช้ / เช่น C:/Users/me/tfp/secrets.toml
```

- `secrets.toml` ต้องมี `[gcp_service_account]`, `GEMINI_API_KEY`, `RESEARCH_USERNAME`, `RESEARCH_PASSWORD`
- `TFP_COOKIE_SECURE=0` ใช้เฉพาะเปิดบนเครื่องตัวเองผ่าน http
- ห้ามส่ง `.env` / `secrets.toml` ให้ใคร และห้าม commit (`.gitignore` กันไว้แล้ว)

## 4. รัน และเปิดใช้

```sh
docker compose -f deploy/compose.yaml --env-file deploy/.env up -d --build
```

ครั้งแรก build ราว 5–15 นาที แล้วเปิด http://localhost:8080

| ทำอะไร | คำสั่ง |
|---|---|
| ปิด (ข้อมูลยังอยู่) | `docker compose -f deploy/compose.yaml --env-file deploy/.env stop` |
| เปิดใหม่ | `docker compose -f deploy/compose.yaml --env-file deploy/.env start` |
| อัปเดตโค้ด | `git pull` แล้ว `docker compose -f deploy/compose.yaml --env-file deploy/.env up -d --build` |
| ดู log | `docker compose -f deploy/compose.yaml --env-file deploy/.env logs --tail=100 api worker` |

**ห้ามใช้ `down -v`** (ลบฐานข้อมูลทั้งหมด)

## ปัญหาที่พบบ่อย

| อาการ | แก้ |
|---|---|
| build หน้าเว็บล้ม `schema.d.ts differ` (Windows) | clone ใหม่หลังมี `.gitattributes` |
| กดปุ่มแล้ว 403 | URL ที่เปิดต้องตรงกับ `TFP_ALLOWED_ORIGINS` ทุกตัวอักษร (localhost กับ 127.0.0.1 ถือว่าต่างกัน) |
| ล็อกอินคณะวิจัยแล้วเด้งออก | ผ่าน http ต้องตั้ง `TFP_COOKIE_SECURE=0` |
| หาไฟล์ secrets ไม่เจอ | `TFP_SECRETS_PATH` ต้องเป็นที่อยู่เต็มของไฟล์ที่มีจริง |
| พอร์ต 8080 ถูกใช้ | เปลี่ยน `TFP_WEB_PORT` และพอร์ตใน `TFP_ALLOWED_ORIGINS` ให้ตรงกัน |

บน Windows / เครื่อง Intel-AMD ผลบางค่า (เช่น backtest) อาจต่างจาก Mac ในทศนิยมท้าย ๆ — ดู `docs/RUNTIME_DIFFERENCES.md`
