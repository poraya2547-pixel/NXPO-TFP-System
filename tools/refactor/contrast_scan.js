// สแกน contrast ของข้อความที่มองเห็นทุกตัวในหน้า (สูตร WCAG 2.x) — คืนรายการที่ต่ำกว่า window.__TFP_MIN_RATIO (ค่าเริ่ม 3)
// สีพื้น = ไล่ขึ้นหา gradient หรือ background-color ที่ทึบ (ผสมชั้นโปร่ง) เฉพาะกล่องที่ครอบข้อความ; gradient ใช้สีที่แย่ที่สุด
// ข้าม: ไอคอน Material, SVG (กราฟ Vega ตรวจแยก), องค์ประกอบ disabled (WCAG ยกเว้น), ข้อความที่ซ่อน
(() => {
  const MIN = window.__TFP_MIN_RATIO || 3;
  const parse = (s) => {
    const m = s && s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  // สีใน gradient ที่ทึบพอจะเป็นพื้นของข้อความ (background-image วาดทับ background-color)
  const opaqueStops = (img) => {
    const m = img && img !== "none" && img.match(/rgba?\([^)]+\)/g);
    return m ? m.map(parse).filter((c) => c[3] > 0.5).map((c) => [c[0], c[1], c[2], 1]) : [];
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const blend = (top, bot) => [0, 1, 2].map((i) => top[i] * top[3] + bot[i] * (1 - top[3])).concat(1);
  // คืนสีพื้นที่เป็นไปได้ทั้งหมดใต้ข้อความ (gradient = หลายสี) จากชั้นที่วาดอยู่ใต้จุดกลางข้อความจริง
  // (elementsFromPoint: จับพื้นที่เป็น element พี่น้องวางซ้อน และไม่นับกล่องแม่ที่ข้อความลอยออกไปนอกกรอบ เช่น ตัวเลข slider)
  // บรรพบุรุษที่ hit test ไม่คืน (tr/thead ของตาราง, pointer-events: none) เติมกลับตามลำดับ DOM
  // ถ้าจุดนั้นไม่มี el เลย (อยู่นอกจอ) ใช้บรรพบุรุษตาม DOM อย่างเดียว
  const bgsOf = (el) => {
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const covers = (e) => { const b = e.getBoundingClientRect(); return x >= b.left && x <= b.right && y >= b.top && y <= b.bottom; };
    const ancestors = [];  // เฉพาะกล่องที่ครอบจุดกลางข้อความ (ตัวเลข slider ลอยนอกปุ่มเลื่อน → ไม่นับปุ่ม)
    for (let e = el; e && e.nodeType === 1; e = e.parentElement)
      if (e === el || e === document.body || e === document.documentElement || covers(e)) ancestors.push(e);
    const stack = document.elementsFromPoint(x, y);
    const i0 = stack.findIndex((e) => e === el || e.contains(el));
    const chain = [];
    let ai = 0;  // บรรพบุรุษถัดไปที่ยังไม่ได้ใส่
    if (i0 >= 0) {
      for (const s of stack.slice(i0)) {
        const k = ancestors.indexOf(s, ai);
        if (k >= 0) { chain.push(...ancestors.slice(ai, k + 1)); ai = k + 1; }
        else if (!el.contains(s)) chain.push(s);  // element พี่น้องที่วาดอยู่ใต้ข้อความ
      }
    }
    chain.push(...ancestors.slice(ai));
    const layers = [];
    let bottom = null;
    for (const e of chain) {
      const cs = getComputedStyle(e);
      const g = opaqueStops(cs.backgroundImage);
      if (g.length) { bottom = g; break; }
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) { if (c[3] >= 1) { bottom = [c]; break; } layers.push(c); }
    }
    return (bottom || [[255, 255, 255, 1]]).map((base) => {
      for (let i = layers.length - 1; i >= 0; i--) base = blend(layers[i], base);
      return base;
    });
  };
  const opacityOf = (el) => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  const rgb = (c) => `rgb(${c.slice(0, 3).map(Math.round).join(",")})`;
  const out = new Map();
  let checked = 0;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    const text = n.textContent.replace(/\s+/g, " ").trim();
    if (text.length < 1) continue;
    const el = n.parentElement;
    if (!el || el.closest('svg,script,style,noscript,[aria-hidden="true"],[disabled],[aria-disabled="true"],#vg-tooltip-element')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility !== "visible" || /Material/i.test(cs.fontFamily.split(",")[0])) continue;
    const op = opacityOf(el);
    if (op < 0.05) continue;
    const fg0 = parse(cs.color);
    if (!fg0) continue;
    checked++;
    let ratio = Infinity, fg, bg;
    for (const b of bgsOf(el)) {  // gradient: ใช้สีที่ contrast แย่ที่สุด
      const f = blend([fg0[0], fg0[1], fg0[2], fg0[3] * op], b);
      const L1 = lum(f), L2 = lum(b);
      const q = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      if (q < ratio) { ratio = q; fg = f; bg = b; }
    }
    if (ratio < MIN) {
      const k = `${text.slice(0, 60)}|${rgb(fg)}|${rgb(bg)}`;
      if (!out.has(k)) out.set(k, { text: text.slice(0, 60), ratio: +ratio.toFixed(2), fg: rgb(fg), bg: rgb(bg),
                                    where: (el.closest("[class*='st-key-']")?.className.match(/st-key-[\w-]+/) || [el.tagName.toLowerCase()])[0] });
    }
  }
  return { scheme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light", checked,
           low: [...out.values()].sort((a, b) => a.ratio - b.ratio) };
})()
