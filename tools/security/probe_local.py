"""ยิงทดสอบความปลอดภัยแบบไม่ทำลายกับเว็บ local (ค่าเริ่ม http://127.0.0.1:8090) — ไม่เรียกบริการภายนอก ไม่กดดึงข้อมูล/Gemini

แต่ละข้อพิมพ์ PASS / FAIL / INFO; exit 1 ถ้ามี FAIL ใช้กับ local หรือเครื่องทดสอบของตัวเองเท่านั้น
ไม่ยิงล็อกอินผิดซ้ำ (จะล็อกการล็อกอินของทุกคนหลัง proxy 15 นาที — ดู SECURITY_REVIEW M-1)

    /opt/anaconda3/envs/idntwww/bin/python -B tools/security/probe_local.py [URL]
"""
import http.client
import json
import secrets
import sys
import urllib.parse

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090"
U = urllib.parse.urlsplit(BASE)
ORIGIN = f"{U.scheme}://{U.netloc}"
results = []


def req(method, path, body=None, headers=None, raw_path=False):
    c = (http.client.HTTPSConnection if U.scheme == "https" else http.client.HTTPConnection)(U.hostname, U.port, timeout=30)
    h = {"Host": U.netloc, **(headers or {})}
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    if data is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    out = (r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
    c.close()
    return out


def check(name, ok, detail=""):
    results.append(("PASS" if ok else "FAIL", name, detail))


def info(name, detail):
    results.append(("INFO", name, detail))


def new_session():
    st, h, b = req("GET", "/api/v1/view")
    cookie = h.get("set-cookie", "").split(";")[0]
    return cookie, json.loads(b)["csrf_token"], h.get("set-cookie", "")


def post(cookie, csrf, body, origin=ORIGIN, extra=None):
    h = {"Cookie": cookie, "X-CSRF-Token": csrf, **(extra or {})}
    if origin:
        h["Origin"] = origin
    return req("POST", "/api/v1/events", body, h)


LEAK = (b"Traceback", b"File \"/", b"/app/app/", b"psycopg", b"sqlalchemy", b"Exception:", b"nginx/1.")


def no_leak(b):
    return not any(s in b for s in LEAK)


# ---------- 1. ไฟล์/เส้นทางที่ไม่ควรเปิด ----------
for p in ["/.env", "/.git/config", "/deploy/compose.yaml", "/private/", "/backend/app/config.py", "/docs", "/redoc",
          "/openapi.json", "/api/docs", "/api/openapi.json", "/api/v1/docs", "/api/v1/openapi.json", "/nginx_status",
          "/server-status", "/api/v1/assets/..%2f..%2fetc%2fpasswd", "/api/v1/assets/%2e%2e/%2e%2e/etc/passwd",
          "/assets/../../etc/passwd", "/api/v1/downloads/..%2f..%2fetc%2fpasswd", "/api/v1/../../etc/passwd"]:
    st, h, b = req("GET", p)
    if p == "/api/v1/openapi.json":  # ตั้งใจเปิด (สัญญา API) ไม่มีค่าลับ — รายงานเป็นข้อสังเกต L-2 ใน SECURITY_REVIEW
        info(f"path {p}", f"{st} เปิดอ่านได้ {len(b)}B")
        continue
    sus = b"root:" in b or b"TFP_" in b or b"swagger" in b.lower() or b"openapi" in b[:200].lower()
    ok = not sus and (st in (400, 403, 404) or (st == 200 and b.lstrip().startswith(b"<!doctype html") and b"swagger" not in b.lower()))
    check(f"path {p}", ok, f"{st} {len(b)}B")

# ---------- 2. HTTP methods ----------
for m in ["TRACE", "PUT", "DELETE", "PATCH"]:
    for p in ["/", "/api/v1/view", "/api/v1/events"]:
        st, h, b = req(m, p)
        check(f"method {m} {p}", 400 <= st < 500 or st == 501, str(st))  # ถูกปฏิเสธ (405/413/...) ไม่ใช่ 2xx/5xx

# ---------- 3. headers ----------
want = ["content-security-policy", "x-content-type-options", "referrer-policy", "permissions-policy"]
for p in ["/", "/api/v1/view", "/api/v1/health", "/does-not-exist", "/api/v1/nope"]:
    st, h, b = req("GET", p)
    miss = [w for w in want if w not in h]
    check(f"headers {p}", not miss and "server" not in h or h.get("server") == "nginx", f"{st} missing={miss} server={h.get('server')}")
st, h, b = req("GET", "/")
check("frame-ancestors / clickjacking", "frame-ancestors" in h.get("content-security-policy", ""), "")
check("CSP ไม่มี unsafe-eval/script unsafe-inline", "unsafe-eval" not in h.get("content-security-policy", "") and
      "script-src 'self';" in h.get("content-security-policy", ""), "")
info("HSTS", h.get("strict-transport-security", "ไม่มี (ต้องตั้งที่ HTTPS proxy ของ IT)"))

# ---------- 4. CORS ----------
st, h, b = req("GET", "/api/v1/view", headers={"Origin": "https://evil.example"})
check("CORS ไม่สะท้อน origin อื่น", "access-control-allow-origin" not in h, h.get("access-control-allow-origin", "-"))
st, h, b = req("OPTIONS", "/api/v1/events", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
check("CORS preflight ไม่อนุญาต origin อื่น", "access-control-allow-origin" not in h, str(st))

# ---------- 5. session/cookie ----------
cookie, csrf, raw = new_session()
token = cookie.split("=", 1)[1]
check("cookie HttpOnly + SameSite", "httponly" in raw.lower() and "samesite" in raw.lower(), raw.split(";", 1)[1].strip())
info("cookie Secure", "มี" if "secure" in raw.lower() else "ไม่มี (local HTTP ตั้ง TFP_COOKIE_SECURE=0 — ระบบจริงต้องเป็น 1)")
check("token ยาวพอ (≥ 32 ตัว)", len(token) >= 32, f"{len(token)} ตัว")
check("csrf ยาวพอ (≥ 32 ตัว)", len(csrf) >= 32, f"{len(csrf)} ตัว")
fake = "tfp_session=" + secrets.token_urlsafe(32)
st, h, b = req("GET", "/api/v1/view", headers={"Cookie": fake})
check("session fixation: token ปลอมไม่ถูกรับ (ออก cookie ใหม่)",
      "set-cookie" in h and h["set-cookie"].split(";")[0] != fake, "")
st, h, b = post(fake, csrf, {"values": {}})
check("POST ด้วย token ปลอม → ถูกปฏิเสธ", st in (401, 403), str(st))
other_cookie, other_csrf, _ = new_session()
st, h, b = post(cookie, other_csrf, {"values": {}})
check("CSRF ของ session อื่นใช้ข้ามไม่ได้", st == 403, str(st))
for o in ["https://evil.example", "null", ORIGIN + ".evil.example", ORIGIN.replace("127.0.0.1", "localhost") + ":1", None]:
    st, h, b = post(cookie, csrf, {"values": {}}, origin=o)
    check(f"origin [{o}] ถูกปฏิเสธ", st == 403, str(st))
st, h, b = req("POST", "/api/v1/events", b"trigger=x", {"Cookie": cookie, "Origin": ORIGIN, "X-CSRF-Token": csrf,
                                                          "Content-Type": "application/x-www-form-urlencoded"})
check("form-urlencoded (CSRF แบบฟอร์ม) ใช้ไม่ได้", st in (400, 403, 415, 422), str(st))

# ---------- 6. ค่าในคำขอผิดรูปแบบ ----------
cookie, csrf, _ = new_session()
cases = {
    "trigger ไม่มีจริง": {"trigger": "no_such_button_" + secrets.token_hex(4), "values": {}},
    "trigger ยาวเกิน": {"trigger": "a" * 5000, "values": {}},
    "trigger มี null byte": {"trigger": "pick_role_visitor\u0000", "values": {}},
    "values ผิดชนิด": {"trigger": None, "values": "not-a-dict"},
    "values ซ้อนลึก": {"values": {"x": json.loads("[" * 200 + "]" * 200)}},
    "key แปลก (__proto__)": {"values": {"__proto__": {"admin": True}, "constructor": 1}},
    "ค่า XSS ในช่องที่ไม่มีจริง": {"values": {"<img src=x onerror=alert(1)>": "<script>alert(1)</script>"}},
    "resume โดยไม่มีงาน": {"resume": True},
    "ฟิลด์เกิน": {"values": {}, "is_admin": True, "role": "research"},
    "ตัวเลขยักษ์": {"values": {"tfp_horizon": 10 ** 400}},
}
for name, body in cases.items():
    raw = json.dumps(body).encode() if name != "ตัวเลขยักษ์" else b'{"values":{"tfp_horizon":1' + b"0" * 400 + b"}}"
    st, h, b = post(cookie, csrf, raw)
    check(f"input: {name}", st != 500 and no_leak(b), f"{st} {b[:90]!r}")
    if st == 200:
        csrf = json.loads(b).get("csrf_token", csrf)
st, h, b = post(cookie, csrf, b"{" + b'"values":{"a":"' + b"x" * 70000 + b'"}}')
check("body ใหญ่เกิน 64KB ถูกตัด", st in (413, 400), str(st))
st, h, b = post(cookie, csrf, b"{not json")
check("JSON เสีย → 4xx ไม่รั่วรายละเอียด", 400 <= st < 500 and no_leak(b), f"{st} {b[:80]!r}")

# ---------- 7. หน้า/สิทธิ์คณะวิจัย ----------
cookie, csrf, _ = new_session()
st, h, b = post(cookie, csrf, {"trigger": "nav_research_home", "values": {"page": "research_home"}})
txt = b.decode("utf-8", "replace")
check("ผู้เยี่ยมชมบังคับเปิดหน้าคณะวิจัยไม่ได้", "ออกจากระบบคณะวิจัย" not in txt and "จัดการข้อมูลอัตโนมัติ" not in txt, str(st))

# ---------- 8. downloads/assets ----------
for p in ["/api/v1/downloads/" + secrets.token_hex(16), "/api/v1/downloads/1", "/api/v1/downloads/0",
          "/api/v1/assets/" + "0" * 64, "/api/v1/assets/" + "a" * 63, "/api/v1/assets/AAAA"]:
    st, h, b = req("GET", p, headers={"Cookie": cookie})
    check(f"ไฟล์ที่ไม่มี/ไม่ใช่ของเรา {p[:40]}", st in (400, 403, 404, 422) and no_leak(b), str(st))

# ---------- 9. Host header ----------
st, h, b = req("GET", "/", headers={"Host": "evil.example"})
check("Host ปลอมไม่ถูกสะท้อนในหน้า", b"evil.example" not in b and "evil.example" not in json.dumps(h), str(st))

for status, name, detail in results:
    print(f"{status:4s} {name}  {detail}")
fails = sum(1 for r in results if r[0] == "FAIL")
print(f"\nรวม {len(results)} ข้อ: PASS {sum(1 for r in results if r[0] == 'PASS')} FAIL {fails} INFO {sum(1 for r in results if r[0] == 'INFO')}")
sys.exit(1 if fails else 0)
