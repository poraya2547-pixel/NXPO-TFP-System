// กราฟ Vega-Lite จาก spec ที่ backend สร้างด้วยตัวสร้าง Altair เดิม — ทำแบบเดียวกับ Streamlit 1.64 (ArrowVegaLiteChart):
// - ธีม "streamlit" แบบสว่างเสมอ (เว็บล็อกธีมสว่าง ดู streamlit-base.css) (styled-components zue + getColors) รวมเข้า spec.config โดย config ของกราฟชนะ
// - ความกว้างวัดจาก element ของกราฟเอง (ResizeObserver → rAF → throttle 100ms) แล้วใส่เป็น spec.width ตอนสร้าง
//   ขนาดเปลี่ยนภายหลังใช้ view.width() ไม่สร้างกราฟใหม่
// - ปรับ spec ฝั่งหน้าเว็บตาม W(): ตัด width/height ที่ ≤ 0, title.limit, padding.bottom = 20, แปลงชื่อสีของธีม
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import embed, { type Result } from "vega-embed";
import { expressionInterpreter } from "vega-interpreter";

type Json = Record<string, unknown>;

// palette ของ Streamlit 1.64 (เฉพาะสีที่กราฟใช้)
const P = {
  white: "#ffffff", gray10: "#fafafa", gray30: "#e6eaf1", gray40: "#d5dae5", gray60: "#a3a8b8", gray70: "#808495",
  gray80: "#555867", gray85: "#31333F", gray100: "#0e1117",
  blue10: "#e4f5ff", blue20: "#c7ebff", blue30: "#a6dcff", blue40: "#83c9ff", blue50: "#60b4ff", blue60: "#3d9df3",
  blue70: "#1c83e1", blue80: "#0068c9", blue90: "#0054a3", blue100: "#004280",
  red30: "#ffc7c7", red40: "#ffabab", red50: "#ff8c8c", red70: "#ff4b4b", red80: "#ff2b2b", red90: "#bd4043",
  red100: "#7d353b", green40: "#7defa1", green70: "#21c354", green80: "#09ab3b", blueGreen80: "#29b09d",
  orange50: "#ffd16a", orange70: "#ffa421", orange80: "#ff8700", yellow70: "#ffe312", yellow80: "#faca2b",
  purple70: "#803df5", purple80: "#6d3fc0",
};
const BLUES = [P.blue10, P.blue20, P.blue30, P.blue40, P.blue50, P.blue60, P.blue70, P.blue80, P.blue90, P.blue100];
const DIVERGING = [P.red100, P.red90, P.red70, P.red50, P.red30, P.blue30, P.blue50, P.blue70, P.blue90, P.blue100];

interface ChartTheme {
  bg: string; heading: string; label: string; grid: string;
  categorical: string[]; sequential: string[]; named: Record<string, string>;
}

// ธีมสว่าง (St) ของ Streamlit: label = gray70, grid = gray30
const LIGHT: ChartTheme = {
  bg: P.white, heading: P.gray85, label: P.gray70, grid: P.gray30,
  categorical: [P.blue80, P.blue40, P.red80, P.red40, P.blueGreen80, P.green40, P.orange80, P.orange50, P.purple80, P.gray40],
  sequential: BLUES,
  named: { red: P.red70, orange: P.orange70, yellow: P.yellow80, green: P.green70, blue: P.blue70, violet: P.purple70,
           gray: P.gray60, grey: P.gray60, primary: P.red70 },
};

// zue(): config ธีม "streamlit" (rem → px ด้วยฐาน 16)
function streamlitConfig(t: ChartTheme): Json {
  return {
    font: '"Source Sans", sans-serif', background: t.bg, fieldTitle: "verbal", autosize: { type: "fit", contains: "padding" },
    title: { align: "left", anchor: "start", color: t.heading, titleFontStyle: "normal", fontWeight: 600, fontSize: 16,
             orient: "top", offset: 26 },
    header: { titleFontWeight: 400, titleFontSize: 16, titleColor: t.label, titleFontStyle: "normal", labelFontSize: 12,
              labelFontWeight: 400, labelColor: t.label, labelFontStyle: "normal" },
    axis: { labelFontSize: 12, labelFontWeight: 400, labelColor: t.label, labelFontStyle: "normal", titleFontWeight: 400,
            titleFontSize: 14, titleColor: t.label, titleFontStyle: "normal", ticks: false, gridColor: t.grid, domain: false,
            domainWidth: 1, domainColor: t.grid, labelFlush: true, labelFlushOffset: 1, labelBound: false, labelLimit: 100,
            titlePadding: 16, labelPadding: 16, labelSeparation: 4, labelOverlap: true },
    legend: { labelFontSize: 14, labelFontWeight: 400, labelColor: t.label, titleFontSize: 14, titleFontWeight: 400,
              titleFontStyle: "normal", titleColor: t.label, titlePadding: 8, labelPadding: 16, columnPadding: 8,
              rowPadding: 4, padding: 8, symbolStrokeWidth: 4 },
    range: { category: t.categorical, diverging: DIVERGING, ramp: t.sequential, heatmap: t.sequential },
    view: { columns: 1, strokeWidth: 0, stroke: "transparent", continuousHeight: 350, continuousWidth: 400 },
    concat: { columns: 1 },
    facet: { columns: 1 },
    mark: { tooltip: { content: "encoding" }, color: t.categorical[0] },
    bar: { binSpacing: 4, discreteBandSize: { band: 0.85 } },
    axisDiscrete: { grid: false },
    axisXPoint: { grid: false },
    axisTemporal: { grid: false },
    axisXBand: { grid: false },
  };
}

const isPlain = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);

// lodash mergeWith({}, base, extra, (a, b) => Array.isArray(b) ? b : undefined)
function merge(dst: Json, src: Json): Json {
  for (const [k, v] of Object.entries(src)) {
    if (v === undefined) continue;
    dst[k] = Array.isArray(v) ? v : isPlain(v) ? merge(isPlain(dst[k]) ? (dst[k] as Json) : {}, v) : v;
  }
  return dst;
}

// F()/I(): ชื่อสีของธีม (red, blue, primary, …) ใน encoding.color.value และ scale.range → สีของธีม
function themeColors(spec: Json, t: ChartTheme) {
  const conv = (v: unknown) => (typeof v === "string" && v.toLowerCase() in t.named ? t.named[v.toLowerCase()] : v);
  const color = isPlain(spec.encoding) ? spec.encoding.color : undefined;
  if (isPlain(color)) {
    if ("value" in color) color.value = conv(color.value);
    if (isPlain(color.scale) && Array.isArray(color.scale.range)) color.scale.range = color.scale.range.map(conv);
  }
  if (Array.isArray(spec.layer)) spec.layer.forEach((s) => isPlain(s) && themeColors(s, t));
  for (const k of ["vconcat", "hconcat", "concat"]) {
    const v = spec[k];
    if (Array.isArray(v)) v.forEach((s) => isPlain(s) && themeColors(s, t));
  }
  if (("facet" in spec || "repeat" in spec) && isPlain(spec.spec)) themeColors(spec.spec, t);
}

// W(): spec ที่ส่งให้ vega-embed (หน้าเดิมไม่มี usermeta/selection จึงไม่มีขั้นตอน H()/U())
function prepareSpec(source: Json, width: number, useContainerWidth: boolean, t: ChartTheme, theme: string | null | undefined) {
  const c = JSON.parse(JSON.stringify(source)) as Json;
  if (typeof c.height === "number" && c.height <= 0) delete c.height;
  if (typeof c.width === "number" && c.width <= 0) delete c.width;
  c.config = theme === "streamlit"
    ? merge(merge({}, streamlitConfig(t)), isPlain(c.config) ? c.config : {})
    : c.config; // หน้าเดิมใช้ theme="streamlit" ทุกกราฟ (Bue() สำหรับ theme อื่นไม่ได้ใช้)
  if (c.title) {
    if (typeof c.title === "string") c.title = { text: c.title };
    const title = c.title as Json;
    title.limit = title.limit ?? Math.max(width - 40, 0);
  }
  if (useContainerWidth && width > 0) {
    c.width = width;
    if (Array.isArray(c.vconcat)) {
      for (const e of c.vconcat) {
        if (isPlain(e) && !["hconcat", "vconcat", "concat", "facet", "repeat"].some((k) => k in e)) e.width = width;
      }
    }
  }
  if (!c.padding) c.padding = {};
  if (isPlain(c.padding) && (c.padding.bottom === undefined || c.padding.bottom === null)) c.padding.bottom = 20;
  themeColors(c, t);
  return c;
}

const EMBED_OPTIONS = {
  actions: false,
  renderer: "svg" as const,
  ast: true, // ไม่ใช้ eval/new Function กับ expression ของ Vega (ใช้ได้กับ CSP ที่ไม่อนุญาต unsafe-eval)
  expr: expressionInterpreter,
  tooltip: { disableDefaultStyle: true }, // สไตล์ tooltip มาจาก #vg-tooltip-element ใน streamlit-base.css
  defaultStyle: false,
};


// useResizeObserver ของ Streamlit: getBoundingClientRect().width, ResizeObserver → rAF → throttle 100ms (ครั้งแรกทันที + ครั้งท้าย)
function useElementWidth(ref: React.RefObject<HTMLDivElement | null>): number {
  const [width, setWidth] = useState(-1);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(el.getBoundingClientRect().width || -1);
    let cooling = false, pending = false, timer = 0, frame = 0;
    const cool = () => {
      cooling = false;
      if (pending) {
        pending = false;
        measure();
        cooling = true;
        timer = window.setTimeout(cool, 100);
      }
    };
    const throttled = () => {
      if (cooling) {
        pending = true;
        return;
      }
      measure();
      cooling = true;
      timer = window.setTimeout(cool, 100);
    };
    measure();
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(throttled);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [ref]);
  return width;
}

export function VegaChart({ spec, theme, useContainerWidth }:
                          { spec: Json; theme?: string | null; useContainerWidth: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useElementWidth(ref);
  const result = useRef<Result | null>(null);
  const viewWidth = useRef(0); // ความกว้างที่ view ใช้อยู่
  const widthNow = useRef(width);
  widthNow.current = width;
  const [ready, setReady] = useState(0);
  const canCreate = !useContainerWidth || width > 0;
  const json = JSON.stringify(spec);

  useLayoutEffect(() => {
    if (!canCreate || !ref.current) return;
    let cancelled = false;
    const w = widthNow.current;
    viewWidth.current = w;
    embed(ref.current, prepareSpec(JSON.parse(json), w, useContainerWidth, LIGHT, theme) as never,
          EMBED_OPTIONS)
      .then(async (r) => {
        if (cancelled) {
          r.finalize();
          return;
        }
        result.current = r;
        await r.view.resize().runAsync();
        if (!cancelled) setReady((n) => n + 1);
      })
      .catch((e) => console.error("vega-embed", e));
    return () => {
      cancelled = true;
      result.current?.finalize();
      result.current = null;
    };
  }, [json, theme, useContainerWidth, canCreate]);

  // ขนาดเปลี่ยน: ปรับความกว้างของ view เดิม (Streamlit resizeView)
  useEffect(() => {
    const r = result.current;
    if (!r || !useContainerWidth || width <= 0 || width === viewWidth.current) return;
    viewWidth.current = width;
    r.view.width(width);
    r.view.resize().runAsync().catch((e) => console.warn("vega resize", e));
  }, [width, ready, useContainerWidth]);

  return (
    <div data-testid="stFullScreenFrame">
      <div className="tfp-chart-frame">
        <div ref={ref} data-testid="stVegaLiteChart"
             className={`stVegaLiteChart${useContainerWidth ? " tfp-container-width" : ""}`} />
      </div>
    </div>
  );
}
