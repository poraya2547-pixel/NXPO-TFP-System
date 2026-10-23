// โครงหน้า (sidebar + เนื้อหา) แบบ Streamlit layout="wide" — เนื้อหาทั้งหมดมาจาก API
// การกระทำ: ส่ง event → ได้หน้าใหม่; ถ้าหน้ารอ job ของ worker จะถาม /pending ทุก 1 วินาทีแล้วส่ง resume เมื่อเสร็จ
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, getPending, getView, postEvent, type EventBody, type View } from "./api/client";
import { IsSidebarContext } from "./render/Markdown";
import { Node, nodeKey, RenderContext } from "./render/Tree";

const POLL_MS = 1000;

// ความกว้าง scrollbar แบบ Streamlit 1.64 (index.*.js mg/hg): กล่อง 50×50 overflow:scroll หาผลต่างของ offsetWidth
// (0 เมื่อ scrollbar ไม่กินที่ เช่น macOS ค่าเริ่มต้น) — ใช้คำนวณ padding ของแถบเมนูที่จอง scrollbar-gutter ทั้งสองข้าง
function scrollbarWidth(): number {
  const e = document.createElement("div");
  e.style.cssText = "position:absolute;top:-9999px;left:-9999px;visibility:hidden;overflow:scroll;width:50px;height:50px";
  document.body.appendChild(e);
  const t = document.createElement("div");
  t.style.cssText = "width:100%;height:100%";
  e.appendChild(t);
  const n = e.offsetWidth - t.offsetWidth;
  e.remove();
  return n;
}

// แถบเมนูแบบ Streamlit 1.64 (initial_sidebar_state="auto"): ซ่อนเมื่อจอกว้าง ≤ 768px คำนวณใหม่ทุกครั้งที่ความกว้างหน้าต่างเปลี่ยน
// ถ้าผู้ใช้กดซ่อน/แสดงเอง จำค่าไว้ใน localStorage (key เดียวกับ Streamlit: stSidebarCollapsed-<หน้า>)
const MD = 768;
const PREF_KEY = "stSidebarCollapsed-tfp";

function readPref(): boolean | null {
  try {
    const v = window.localStorage.getItem(PREF_KEY);
    return v === null ? null : v === "true";
  } catch {
    return null;
  }
}

function savePref(collapsed: boolean) {
  try {
    window.localStorage.setItem(PREF_KEY, String(collapsed));
  } catch {
    // เบราว์เซอร์ไม่ให้ใช้ localStorage — ค่าอยู่เฉพาะหน้านี้
  }
}

// ความกว้างหน้าต่างจาก event resize แบบ throttle 100ms (ครั้งแรกทันที + ครั้งท้าย) เหมือน WindowDimensionsProvider
function useWindowWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    let cooling = false, pending = false, timer = 0;
    const measure = () => setWidth(window.innerWidth);
    const cool = () => {
      cooling = false;
      if (pending) {
        pending = false;
        measure();
        cooling = true;
        timer = window.setTimeout(cool, 100);
      }
    };
    const onResize = () => {
      if (cooling) {
        pending = true;
        return;
      }
      measure();
      cooling = true;
      timer = window.setTimeout(cool, 100);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      window.clearTimeout(timer);
    };
  }, []);
  return width;
}

export default function App() {
  const [view, setView] = useState<View | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const windowWidth = useWindowWidth();
  const [collapsed, setCollapsed] = useState(() => readPref() ?? window.innerWidth <= MD);
  const sidebarRef = useRef<HTMLElement>(null);
  // padding ของแถบเมนู = max(sw, spacing.xl − sw) ตาม Streamlit 1.64 (index.*.js ay) — sw วัดใหม่เมื่อ devicePixelRatio เปลี่ยน
  const dpr = window.devicePixelRatio;
  const sidebarPad = useMemo(() => {
    const sw = scrollbarWidth();
    return `max(${sw}px, calc(1.25rem - ${sw}px))`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dpr]);
  const appRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);

  const show = useCallback((v: View) => {
    setView(v);
    setError(null);
    const title = v.page_config?.page_title;
    if (typeof title === "string") document.title = title;
  }, []);

  const send = useCallback(async (ev: EventBody) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      show(await postEvent(ev));
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (e instanceof ApiError && e.status === 403) {
        try {
          show(await getView()); // CSRF/session เปลี่ยน (เช่นหมดอายุ) — โหลดหน้าใหม่
        } catch {
          // แสดงข้อความ error เดิม
        }
      }
      // show(getView()) clears errors; keep the failed action visible after recovery.
      setError(message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [show]);

  useEffect(() => {
    getView().then(show).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [show]);

  useLayoutEffect(() => {
    setCollapsed(readPref() ?? windowWidth <= MD);
  }, [windowWidth]);

  const toggleSidebar = useCallback((next: boolean) => {
    setCollapsed(next);
    savePref(next);
  }, []);

  // จอขนาดมือถือ: กดนอกแถบเมนู (ภายในแอป) แล้วแถบเมนูปิด และจำค่า
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node | null;
      if (!target || collapsed || windowWidth > MD - 0.02) return;
      if (!sidebarRef.current?.contains(target) && appRef.current?.contains(target)) toggleSidebar(true);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [collapsed, windowWidth, toggleSidebar]);

  // หน้ากำลังรอ job: ถามสถานะจนเสร็จแล้วรันหน้าต่อ
  useEffect(() => {
    if (!view?.pending) return;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      try {
        const p = await getPending();
        if (!p.pending || p.status === "succeeded" || p.status === "failed") {
          await send({ resume: true });
          return;
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
      if (!stop) timer = window.setTimeout(tick, POLL_MS);
    };
    let timer = window.setTimeout(tick, POLL_MS);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [view, send]);

  const hasSidebar = !!view && view.sidebar.children.length > 0;
  return (
    <RenderContext.Provider value={{ send, busy }}>
      <div ref={appRef} className="stApp streamlit-wide" data-testid="stApp"
           data-test-script-state={busy ? "running" : "notRunning"}>
        <div className="stAppViewContainer appview-container" data-testid="stAppViewContainer" data-layout="wide">
          {hasSidebar ? (
            <section ref={sidebarRef} className={`stSidebar${collapsed ? " tfp-collapsed" : ""}`}
                     data-testid="stSidebar" aria-expanded={!collapsed}>
              <div data-testid="stSidebarContent" style={{ paddingLeft: sidebarPad, paddingRight: sidebarPad }}>
                <div data-testid="stSidebarHeader">
                  <div data-testid="stLogoSpacer" />
                  <div data-testid="stSidebarCollapseButton">
                    <button type="button" className="tfp-icon-btn" aria-label="ซ่อนแถบเมนู"
                            onClick={() => toggleSidebar(true)}>
                      <span className="material-symbols-rounded">keyboard_double_arrow_left</span>
                    </button>
                  </div>
                </div>
                <div data-testid="stSidebarUserContent">
                  {/* Streamlit 1.64 มี div คั่นระหว่าง stSidebarUserContent กับ stVerticalBlock — CSS เดิมของหน้าขึ้นกับโครงนี้ */}
                  <div>
                    <div className="stVerticalBlock" data-testid="stVerticalBlock">
                      <IsSidebarContext.Provider value={true}>
                        {view!.sidebar.children.map((n, i) => <Node key={nodeKey(n, i)} n={n} />)}
                      </IsSidebarContext.Provider>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          ) : null}
          <section className="stMain" data-testid="stMain">
            {/* โครงแถบหัวแบบ Streamlit 1.64: ปุ่มแสดงแถบเมนูคือ stExpandSidebarButton ใน stToolbar
                (CSS ของหน้าเดิมอ้าง collapsedControl ของ Streamlit รุ่นเก่า ซึ่งไม่ตรงกับ 1.64 — ปุ่มจึงเป็นแบบปกติ)
                ไม่มีปุ่ม Deploy และเมนู ⋮ ของ Streamlit (ดู B-list ใน STEP_04) */}
            <header className="stAppHeader" data-testid="stHeader">
              <div className="stAppToolbar" data-testid="stToolbar">
                <div className="tfp-toolbar">
                  <div className="tfp-toolbar-left">
                    {hasSidebar && collapsed ? (
                      <div className="tfp-expand-sidebar">
                        <button type="button" {...({ kind: "headerNoPadding" } as Record<string, string>)}
                                data-testid="stExpandSidebarButton" className="tfp-header-btn"
                                aria-label="แสดงแถบเมนู" onClick={() => toggleSidebar(false)}>
                          <span className="tfp-header-icon">
                            <span data-testid="stIconMaterial" className="material-symbols-rounded" translate="no">
                              keyboard_double_arrow_right
                            </span>
                          </span>
                        </button>
                      </div>
                    ) : null}
                  </div>
                  <div className="tfp-toolbar-right">
                    {busy || view?.pending ? (
                      <span className="tfp-running" data-testid="stStatusWidget">กำลังทำงาน…</span>
                    ) : null}
                  </div>
                </div>
              </div>
            </header>
            <div className="stMainBlockContainer block-container" data-testid="stMainBlockContainer">
              {error ? <div className="tfp-api-error" role="alert">{error}</div> : null}
              {view ? (
                <div className="stVerticalBlock" data-testid="stVerticalBlock">
                  {view.main.children.map((n, i) => <Node key={nodeKey(n, i)} n={n} />)}
                </div>
              ) : !error ? <div className="tfp-loading">กำลังโหลด…</div> : null}
            </div>
          </section>
        </div>
      </div>
    </RenderContext.Provider>
  );
}
