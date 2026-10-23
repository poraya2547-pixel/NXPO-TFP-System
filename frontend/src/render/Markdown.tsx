// แสดงข้อความ Markdown แบบ st.markdown: allow_html=true ให้ HTML ของหน้าเดิมผ่านได้ (หลังกรองด้วย DOMPurify)
// allow_html=false แสดง HTML ในข้อความเป็นตัวอักษร (เหมือน Streamlit ที่ไม่ render HTML เมื่อไม่อนุญาต)
import slugify from "@sindresorhus/slugify";
import DOMPurify from "dompurify";
import { Marked } from "marked";
import { createContext, useContext, useEffect, useMemo, useRef } from "react";

// Streamlit ไม่ใส่ลิงก์หัวข้อ (และไม่ครอบ stHeadingWithActionElements) เมื่ออยู่ใน sidebar
export const IsSidebarContext = createContext(false);

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

const withHtml = new Marked({ gfm: true, breaks: false });
const textOnly = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    html(token) {
      return escapeHtml(token.text);
    },
  },
});

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.getAttribute("href")) {
    node.setAttribute("target", node.getAttribute("href")!.trim().startsWith("#") ? "_self" : "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

// DOMPurify ลบ <style> ทั้งก้อนถ้าในข้อความมี "<" ตามด้วยตัวอักษร (กัน mXSS) — CSS ของหน้าเดิมมีคำอธิบาย
// ในคอมเมนต์อย่าง "<p>/<span>" จึงตัดเฉพาะคอมเมนต์ CSS ออกก่อนกรอง (คอมเมนต์ไม่มีผลต่อการแสดงผล)
function stripCssComments(html: string): string {
  return html.replace(/(<style[^>]*>)([\s\S]*?)(<\/style>)/gi,
    (_m, open: string, css: string, close: string) => open + css.replace(/\/\*[\s\S]*?\*\//g, "") + close);
}

// xxHash32 (seed 43981) ของข้อความ UTF-8 — Streamlit ใช้เป็น id หัวข้อเมื่อ slug ว่าง (เช่นหัวข้อภาษาไทยล้วน)
function xxh32(text: string, seed: number): number {
  const d = new TextEncoder().encode(text);
  const P1 = 2654435761, P2 = 2246822519, P3 = 3266489917, P4 = 668265263, P5 = 374761393;
  const rotl = (x: number, r: number) => ((x << r) | (x >>> (32 - r))) >>> 0;
  const u32 = (i: number) => (d[i] | (d[i + 1] << 8) | (d[i + 2] << 16) | (d[i + 3] << 24)) >>> 0;
  const n = d.length;
  let i = 0, h: number;
  if (n >= 16) {
    const v = [(seed + P1 + P2) >>> 0, (seed + P2) >>> 0, seed >>> 0, (seed - P1) >>> 0];
    while (i <= n - 16) {
      for (let k = 0; k < 4; k++, i += 4) v[k] = Math.imul(rotl((v[k] + Math.imul(u32(i), P2)) >>> 0, 13), P1) >>> 0;
    }
    h = (rotl(v[0], 1) + rotl(v[1], 7) + rotl(v[2], 12) + rotl(v[3], 18)) >>> 0;
  } else {
    h = (seed + P5) >>> 0;
  }
  h = (h + n) >>> 0;
  for (; i + 4 <= n; i += 4) h = Math.imul(rotl((h + Math.imul(u32(i), P3)) >>> 0, 17), P4) >>> 0;
  for (; i < n; i++) h = Math.imul(rotl((h + Math.imul(d[i], P5)) >>> 0, 11), P1) >>> 0;
  h ^= h >>> 15;
  h = Math.imul(h, P2) >>> 0;
  h ^= h >>> 13;
  h = Math.imul(h, P3) >>> 0;
  h ^= h >>> 16;
  return h >>> 0;
}

// Streamlit 1.64 (StreamlitMarkdown Fp): slugify ของข้อความหัวข้อ ถ้าว่างใช้ xxHash32 เป็นเลขฐาน 16
export function headingAnchor(text: string): string {
  if (!text) return "";
  const slug = slugify(text);
  return slug.length > 0 ? slug : xxh32(text, 43981).toString(16);
}

const LINK_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
  'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M15 7h3a5 5 0 0 1 5 5 5 5 0 0 1-5 5h-3m-6 0H6a5 5 0 0 1-5-5 5 5 0 0 1 5-5h3"></path>' +
  '<line x1="8" y1="12" x2="16" y2="12"></line></svg>';
let headingSeq = 0;

export function renderMarkdown(body: string, allowHtml: boolean, inSidebar = false): string {
  const html = (allowHtml ? withHtml : textOnly).parse(allowHtml ? stripCssComments(body) : body,
                                                        { async: false }) as string;
  const frag = DOMPurify.sanitize(html, {
    FORCE_BODY: true, // คง <style> ที่อยู่ต้นข้อความ (CSS ของหน้าเดิม)
    ADD_TAGS: ["style"],
    FORBID_TAGS: ["script", "iframe", "object", "embed", "form", "input", "button", "textarea", "select"],
    FORBID_ATTR: ["srcdoc", "formaction"],
    RETURN_DOM_FRAGMENT: true,
  });
  // Streamlit ทำกับหัวข้อทุกระดับ (รวม <h2> ใน HTML ของหน้า): ข้อความอยู่ใน span[data-heading-text]
  // นอก sidebar: ครอบด้วย div[stHeadingWithActionElements], id = anchor, aria-labelledby และลิงก์หัวข้อ (เห็นตอน hover)
  // ลิงก์ท้ายหัวข้อมีผลต่อการตัดบรรทัด (text-wrap: pretty) จึงต้องมีเหมือนเดิม
  frag.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((h) => {
    const span = document.createElement("span");
    span.setAttribute("data-heading-text", "");
    while (h.firstChild) span.appendChild(h.firstChild);
    h.appendChild(span);
    if (inSidebar) return;
    const anchor = headingAnchor(span.textContent ?? "");
    if (anchor) {
      const spanId = `tfp-heading-${++headingSeq}`;
      span.id = spanId;
      h.id = anchor;
      h.setAttribute("aria-labelledby", spanId);
      const actions = document.createElement("span");
      actions.setAttribute("data-testid", "stHeaderActionElements");
      const link = document.createElement("a");
      link.setAttribute("href", `#${anchor}`);
      link.setAttribute("aria-label", "Link to heading");
      link.innerHTML = LINK_ICON;
      actions.appendChild(link);
      h.appendChild(actions);
    }
    const wrap = document.createElement("div");
    wrap.setAttribute("data-testid", "stHeadingWithActionElements");
    h.replaceWith(wrap);
    wrap.appendChild(h);
  });
  const holder = document.createElement("div");
  holder.appendChild(frag);
  return holder.innerHTML;
}

export function Markdown({ body, allowHtml, caption }: { body: string; allowHtml: boolean; caption?: boolean }) {
  const inSidebar = useContext(IsSidebarContext);
  const html = useMemo(() => renderMarkdown(body, allowHtml, inSidebar), [body, allowHtml, inSidebar]);
  const ref = useRef<HTMLDivElement>(null);
  // เปิดหน้าด้วย #anchor ของหัวข้อ → เลื่อนไปที่หัวข้อนั้น (Streamlit scrollIntoView)
  useEffect(() => {
    const hash = decodeURIComponent(window.location.hash.slice(1));
    if (!hash || !ref.current) return;
    const target = [...ref.current.querySelectorAll("h1, h2, h3, h4, h5, h6")].find((h) => h.id === hash);
    target?.scrollIntoView(true);
  }, [html]);
  return (
    <div
      ref={ref}
      data-testid={caption ? "stCaptionContainer" : "stMarkdownContainer"}
      className={caption ? "tfp-caption" : "tfp-md"}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
