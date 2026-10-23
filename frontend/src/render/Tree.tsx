// แสดง element tree จาก API เป็น DOM ที่โครงสร้าง/คลาสใกล้ Streamlit 1.64 เพื่อให้ CSS เดิมของหน้า (ที่อ้าง data-testid,
// .st-key-<key>, .stButton ฯลฯ) ใช้ได้เหมือนเดิม — การกระทำทุกอย่างส่งกลับไปให้ backend รันโค้ดหน้าเดิม ไม่คำนวณในเบราว์เซอร์
import { createContext, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState,
  type KeyboardEvent, type ReactNode } from "react";
import type { Element, EventBody } from "../api/client";
import { Markdown } from "./Markdown";
import { VegaChart } from "./VegaChart";

type Send = (ev: EventBody) => void;
type Value = boolean | number | string | number[] | null;

interface Ctx {
  send: Send;
  busy: boolean;
}

export const RenderContext = createContext<Ctx>({ send: () => {}, busy: false });

interface FormState {
  id: string;
  values: () => Record<string, Value>;
  set: (id: string, v: Value) => void;
  submit: () => void; // Enter ในช่องข้อความ = กดปุ่ม submit ปุ่มแรกของฟอร์ม (Streamlit enter_to_submit)
  canSubmit: boolean; // ปุ่ม submit แรกมีและกดได้ (Streamlit allowFormEnterToSubmit) — ใช้กับข้อความแนะนำใต้ช่อง
}

const FormContext = createContext<FormState | null>(null);

type Of<T extends Element["type"]> = Extract<Element, { type: T }>;

// Streamlit 1.64: "st-key-" + key ที่ตัดช่องว่างหัวท้าย แล้วแทนอักขระนอก [a-zA-Z0-9_-] ด้วย "-" (ทีละ UTF-16 code unit)
function keyClass(key?: string | null) {
  return key ? " st-key-" + key.trim().replace(/[^a-zA-Z0-9_-]/g, "-") : "";
}

/** ส่งค่า widget: ในฟอร์มเก็บไว้ก่อน (ส่งพร้อมปุ่ม submit) นอกฟอร์มส่งทันที */
function useCommit(id: string): (v: Value) => void {
  const { send } = useContext(RenderContext);
  const form = useContext(FormContext);
  return (v: Value) => (form ? form.set(id, v) : send({ values: { [id]: v } }));
}

function ElementContainer({ children, wkey, width }: { children: ReactNode; wkey?: string | null; width?: string }) {
  return (
    <div className={`stElementContainer element-container${keyClass(wkey)}`} data-testid="stElementContainer"
         data-stale="false" style={width ? { width } : undefined}>
      {children}
    </div>
  );
}

function Label({ text, help, visibility, as = "label", htmlFor }: { text: string; help?: string | null;
                                                                       visibility: string; as?: "label" | "div";
                                                                       htmlFor?: string }) {
  if (visibility === "collapsed") return null;
  const Tag = as;
  return (
    <Tag data-testid="stWidgetLabel" className={`tfp-label${visibility === "hidden" ? " tfp-hidden" : ""}`}
         htmlFor={as === "label" ? htmlFor : undefined}>
      <span aria-hidden="true"><Markdown body={text} allowHtml={false} /></span>
      {help ? (
        // Streamlit 1.64: ไอคอนช่วยเหลือชิดขวาสุดของแถว label แสดงข้อความเมื่อชี้/โฟกัส
        <div className="tfp-label-help">
          <span data-testid="stTooltipIcon" className="stTooltipIcon">
            <span data-testid="stTooltipHoverTarget" className="tfp-tooltip-target">
              <button type="button" aria-label={`Help for ${text}`} className="tfp-help-btn">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                     aria-hidden="true" focusable="false">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </button>
              <div data-testid="stTooltipContent" className="tfp-tooltip" role="tooltip">
                <Markdown body={help} allowHtml={false} />
              </div>
            </span>
          </span>
        </div>
      ) : null}
    </Tag>
  );
}

// ไอคอนในปุ่มแบบ DynamicIcon ของ Streamlit 1.64: span(flex 16px) > span[stIconMaterial] ขนาด 1rem
function MaterialIcon({ icon }: { icon?: string | null }) {
  if (!icon) return null;
  const m = /^:material\/([a-z0-9_]+):$/.exec(icon);
  return (
    <span className="tfp-icon-wrap">
      {m ? <span data-testid="stIconMaterial" className="material-symbols-rounded" translate="no">{m[1]}</span>
         : <span data-testid="stIconEmoji">{icon}</span>}
    </span>
  );
}

// ===================== ข้อความ =====================
function MarkdownEl({ n }: { n: Of<"markdown"> }) {
  return (
    <ElementContainer>
      <div className="stMarkdown" data-testid="stMarkdown">
        <div><Markdown body={n.body} allowHtml={n.allow_html} caption={n.kind === "caption"} /></div>
      </div>
    </ElementContainer>
  );
}

const ALERT_TESTID = { info: "stAlertContentInfo", success: "stAlertContentSuccess", warning: "stAlertContentWarning",
                       error: "stAlertContentError" } as const;

function AlertEl({ n }: { n: Of<"alert"> }) {
  return (
    <ElementContainer>
      <div className="stAlert" data-testid="stAlert">
        <div role={n.kind === "error" ? "alert" : "status"} data-testid="stAlertContainer"
             className={`stAlertContainer tfp-alert-${n.kind}`}>
          <div data-testid={ALERT_TESTID[n.kind]}>
            {n.icon ? <span className="tfp-alert-icon">{n.icon}</span> : null}
            <div><Markdown body={n.body} allowHtml={false} /></div>
          </div>
        </div>
      </div>
    </ElementContainer>
  );
}

// ===================== ปุ่ม =====================
/** โครงในปุ่มแบบ Streamlit: div(flex กลาง) > span(flex, gap) > span(contents) > ข้อความ */
function ButtonLabel({ icon, label }: { icon?: string | null; label: string }) {
  return (
    <div className="tfp-btn-inner">
      <span data-has-shortcut="false">
        <MaterialIcon icon={icon} />
        <span style={{ display: "contents" }}><Markdown body={label} allowHtml={false} /></span>
      </span>
    </div>
  );
}

function ButtonEl({ n }: { n: Of<"button"> }) {
  const { send, busy } = useContext(RenderContext);
  const form = useContext(FormContext);
  const onClick = () => {
    if (n.is_form_submitter && form) send({ trigger: n.id, values: form.values() });
    else send({ trigger: n.id });
  };
  // ปุ่ม submit ของฟอร์มใน Streamlit 1.64: kind = <type>FormSubmit และมี div คั่นก่อน stFormSubmitButton
  const kind = n.is_form_submitter ? `${n.kind}FormSubmit` : n.kind;
  const button = (
    <button type="button" {...kindAttr(kind)} data-testid={`stBaseButton-${kind}`} title={n.help ?? undefined}
            className={`tfp-btn tfp-btn-${n.kind}${n.use_container_width ? " tfp-stretch" : ""}`}
            disabled={n.disabled || busy} onClick={onClick}>
      <ButtonLabel icon={n.icon} label={n.label} />
    </button>
  );
  return (
    <ElementContainer wkey={keyOf(n.id)} width={n.use_container_width ? "100%" : "fit-content"}>
      {n.is_form_submitter ? (
        <div className="tfp-submit-wrap">
          <div className="stFormSubmitButton" data-testid="stFormSubmitButton">{button}</div>
        </div>
      ) : (
        <div className="stButton" data-testid="stButton">{button}</div>
      )}
    </ElementContainer>
  );
}

function DownloadEl({ n }: { n: Of<"download_button"> }) {
  const { send, busy } = useContext(RenderContext);
  const onClick = () => {
    const a = document.createElement("a");
    a.href = n.url;
    a.download = n.file_name ?? "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    send({ trigger: n.id }); // Streamlit 1.64: กดดาวน์โหลดแล้วรันหน้าใหม่ (on_click="rerun")
  };
  return (
    <ElementContainer wkey={keyOf(n.id)} width={n.use_container_width ? "100%" : "fit-content"}>
      <div className="stDownloadButton" data-testid="stDownloadButton">
        <button type="button" {...kindAttr(n.kind)} data-testid={`stBaseButton-${n.kind}`} title={n.help ?? undefined}
                className={`tfp-btn tfp-btn-${n.kind}${n.use_container_width ? " tfp-stretch" : ""}`}
                disabled={n.disabled || busy} onClick={onClick}>
          <ButtonLabel icon={n.icon} label={n.label} />
        </button>
      </div>
    </ElementContainer>
  );
}

// ===================== widget =====================
function kindAttr(kind: string): Record<string, string> {
  return { kind }; // Streamlit ใส่ attribute kind ที่ปุ่ม (CSS ของหน้าเดิมอ้าง [kind="primary"])
}

function keyOf(id: string): string | null {
  return id.startsWith("$$auto-") ? null : id;
}

function SelectboxEl({ n }: { n: Of<"selectbox"> }) {
  const commit = useCommit(n.id);
  const { busy } = useContext(RenderContext);
  const [local, setLocal] = useState(n.index);
  useEffect(() => setLocal(n.index), [n.index, n.id]);
  return (
    <ElementContainer wkey={keyOf(n.id)}>
      <div className="stSelectbox" data-testid="stSelectbox">
        <Label text={n.label} help={n.help} visibility={n.label_visibility} />
        <div className="react-aria-ComboBox">
          <div role="group" className="tfp-field tfp-select">
            <select aria-label={n.label} value={local ?? ""} disabled={n.disabled || busy}
                    onChange={(e) => {
                      const v = e.target.value === "" ? null : Number(e.target.value);
                      setLocal(v);
                      commit(v);
                    }}>
              {local === null ? <option value="">{n.placeholder ?? "Choose an option"}</option> : null}
              {n.options.map((o, i) => <option key={i} value={i}>{o}</option>)}
            </select>
            <span className="tfp-select-chevron" aria-hidden="true">
              <svg viewBox="0 0 24 24" height="1.25rem" width="1.25rem" aria-hidden="true" focusable="false"
                   fill="currentColor" xmlns="http://www.w3.org/2000/svg">
                <path fill="none" d="M0 0h24v24H0V0z" />
                <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z" />
              </svg>
            </span>
          </div>
        </div>
      </div>
    </ElementContainer>
  );
}

// multiselect แบบ Streamlit 1.64 (Multiselect.*.js: react-aria ComboBox) — โครงและค่าจากแอป harvest (private/verification/step6-harvest/)
const CHEVRON_ICON = (
  <svg viewBox="0 0 24 24" height="1.25rem" width="1.25rem" aria-hidden="true" focusable="false"
       fill="currentColor" xmlns="http://www.w3.org/2000/svg">
    <path fill="none" d="M0 0h24v24H0V0z" />
    <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z" />
  </svg>
);
const CLEAR_ICON = (
  <svg viewBox="0 0 24 24" height="1rem" width="1rem" aria-hidden="true" focusable="false" fill="currentColor"
       xmlns="http://www.w3.org/2000/svg">
    <path fill="none" d="M0 0h24v24H0V0z" />
    <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm4.29 12.89a.996.996 0 11-1.41 1.41L12 13.41 9.11 16.3a.996.996 0 11-1.41-1.41L10.59 12 7.71 9.11A.996.996 0 119.12 7.7L12 10.59l2.89-2.89a.996.996 0 111.41 1.41L13.41 12l2.88 2.89z" />
  </svg>
);
const TAG_REMOVE_ICON = (
  <svg aria-hidden="true" height="0.5em" width="0.5em" viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg">
    <path d="M9 1L5 5M1 9L5 5M5 5L1 1M5 5L9 9" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
  </svg>
);

function MultiselectEl({ n }: { n: Of<"multiselect"> }) {
  const commit = useCommit(n.id);
  const { busy } = useContext(RenderContext);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [local, setLocal] = useState<number[]>(n.value);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  useEffect(() => setLocal(n.value), [JSON.stringify(n.value), n.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // ระหว่างรอคำตอบ (busy) กดไม่ได้ แต่หน้าตาแบบ "ปิดใช้งาน" ใช้เฉพาะเมื่อ widget ถูกปิดจริง (Streamlit ไม่ทำให้ widget จางระหว่าง rerun)
  const locked = n.disabled || busy;
  const update = (v: number[]) => {
    setLocal(v);
    commit(v);
  };
  // รายการที่เลือกได้ = ตัวที่ยังไม่ได้เลือก กรองด้วยข้อความที่พิมพ์ (ไม่สนตัวพิมพ์เล็กใหญ่)
  const q = query.trim().toLowerCase();
  const choices = n.options.map((o, i) => [o, i] as const)
    .filter(([o, i]) => !local.includes(i) && (!q || o.toLowerCase().includes(q)));
  const pick = (i: number) => {
    update([...local, i]);
    setQuery("");
    setActive(0);
  };
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) setOpen(true);
      else if (choices.length) setActive((a) => (a + (e.key === "ArrowDown" ? 1 : choices.length - 1)) % choices.length);
    } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      if (open && choices[active]) {
        e.preventDefault();
        pick(choices[active][1]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    } else if (e.key === "Backspace" && !query && local.length) {
      e.preventDefault();
      update(local.slice(0, -1));
    }
  };
  return (
    <ElementContainer wkey={keyOf(n.id)}>
      <div className="stMultiSelect" data-testid="stMultiSelect">
        <Label text={n.label} help={n.help} visibility={n.label_visibility} />
        <div className="react-aria-ComboBox tfp-ms" ref={rootRef}>
          <div role="group" className="tfp-ms-field" data-disabled={n.disabled || undefined}
               onClick={(e) => {
                 if (locked || (e.target as HTMLElement).closest("button, [data-tag]")) return;
                 inputRef.current?.focus();
                 setOpen(true);
               }}>
            <div data-testid="stMultiSelectTagsContainer">
              {local.length ? (
                <span role="group" aria-label="Selected values" className="tfp-ms-values">
                  {local.map((i, k) => (
                    <span key={i} className="tfp-ms-tag" aria-label={n.options[i]} data-tag="" data-tag-index={k}
                          tabIndex={k === 0 && !n.disabled ? 0 : -1}>
                      <span className="tfp-ms-tag-text" title={n.options[i]}>{n.options[i]}</span>
                      {!n.disabled ? (
                        <button type="button" aria-label={`Remove ${n.options[i]}`} tabIndex={-1} disabled={busy}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  update(local.filter((x) => x !== i));
                                }}>{TAG_REMOVE_ICON}</button>
                      ) : null}
                    </span>
                  ))}
                </span>
              ) : null}
              <input ref={inputRef} className="tfp-ms-input" type="text" role="combobox" aria-label={n.label}
                     aria-autocomplete="list" aria-expanded={open} aria-controls={open ? listId : undefined}
                     autoComplete="off" spellCheck={false} disabled={locked} value={query}
                     placeholder={local.length ? "" : (n.placeholder ?? "Choose options")}
                     onChange={(e) => {
                       setQuery(e.target.value);
                       setActive(0);
                       setOpen(true);
                     }}
                     onKeyDown={onKey} />
            </div>
            {local.length && !n.disabled ? (
              <button type="button" className="tfp-ms-clear" aria-label="Clear all" disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation();
                        update([]);
                      }}>{CLEAR_ICON}</button>
            ) : null}
            <button type="button" className="tfp-ms-open" aria-label="Open" aria-haspopup="listbox" aria-expanded={open}
                    tabIndex={-1} disabled={locked}
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpen((o) => !o);
                      inputRef.current?.focus();
                    }}>{CHEVRON_ICON}</button>
          </div>
          {open && !locked ? (
            <div data-testid="stMultiSelectDropdown">
              <div id={listId} role="listbox" aria-label={n.label} aria-multiselectable="true" className="tfp-ms-list">
                {choices.length ? choices.map(([o, i], k) => (
                  <div key={i} role="option" aria-selected="false" className="tfp-ms-option"
                       data-focused={k === active || undefined}
                       onMouseEnter={() => setActive(k)}
                       onMouseDown={(e) => e.preventDefault()}
                       onClick={() => pick(i)}>
                    <div>{o}</div>
                  </div>
                )) : <div className="tfp-ms-empty">No results</div>}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </ElementContainer>
  );
}

function formatNumber(v: number, fmt: string, isInt: boolean): string {
  const m = /%0?\.?(\d+)?([df])/.exec(fmt);
  if (!m || isInt || m[2] === "d") return String(Math.round(v));
  return v.toFixed(Number(m[1] ?? 2));
}

function NumberInputEl({ n }: { n: Of<"number_input"> }) {
  const commit = useCommit(n.id);
  const { busy } = useContext(RenderContext);
  const [text, setText] = useState(formatNumber(n.value, n.format, n.int));
  const [focused, setFocused] = useState(false); // มี focus และ widget กว้างพอแสดงข้อความแนะนำ
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    setText(formatNumber(n.value, n.format, n.int));
    setDirty(false);
  }, [n.value, n.id, n.format, n.int]);
  const clamp = (v: number) => Math.min(n.max ?? Infinity, Math.max(n.min ?? -Infinity, v));
  const send = (v: number) => {
    setDirty(false);
    if (!Number.isFinite(v)) return setText(formatNumber(n.value, n.format, n.int));
    const c = clamp(n.int ? Math.round(v) : v);
    setText(formatNumber(c, n.format, n.int));
    if (c !== n.value) commit(c);
  };
  const step = (dir: 1 | -1) => send(Number((n.value + dir * n.step).toFixed(10)));
  return (
    <ElementContainer wkey={keyOf(n.id)}>
      <div className="stNumberInput" data-testid="stNumberInput">
        <Label text={n.label} help={n.help} visibility={n.label_visibility} />
        <div className="react-aria-TextField">
          <div data-testid="stNumberInputContainer" className="tfp-field tfp-number">
            <input type="number" data-testid="stNumberInputField" aria-label={n.label} value={text} step={n.step}
                   min={n.min ?? undefined} max={n.max ?? undefined} disabled={n.disabled || busy}
                   onChange={(e) => {
                     setText(e.target.value);
                     setDirty(true);
                   }}
                   onFocus={(e) => setFocused(wideWidget(e))}
                   onBlur={() => {
                     setFocused(false);
                     send(Number(text));
                   }}
                   onKeyDown={(e) => e.key === "Enter" && send(Number(text))} />
            <div className="tfp-steps">
              <button type="button" data-testid="stNumberInputStepDown" aria-label="Decrement"
                      disabled={n.disabled || busy || (n.min !== null && n.min !== undefined && n.value <= n.min)}
                      onClick={() => step(-1)}>
                <svg viewBox="0 0 8 8" aria-hidden="true" focusable="false" fill="currentColor"
                     xmlns="http://www.w3.org/2000/svg"><path d="M0 3v2h8V3H0z" /></svg>
              </button>
              <button type="button" data-testid="stNumberInputStepUp" aria-label="Increment"
                      disabled={n.disabled || busy || (n.max !== null && n.max !== undefined && n.value >= n.max)}
                      onClick={() => step(1)}>
                <svg viewBox="0 0 8 8" aria-hidden="true" focusable="false" fill="currentColor"
                     xmlns="http://www.w3.org/2000/svg"><path d="M3 0v3H0v2h3v3h2V5h3V3H5V0H3z" /></svg>
              </button>
            </div>
          </div>
        </div>
        {/* กล่องห่อต่อจากช่อง (ไม่กำหนด top/bottom) เว้นที่ปุ่ม +/− (NumberInput e1rv0tzo7: numberInputControlsWidth × 2) */}
        {focused ? (
          <div className="tfp-instr-wrap tfp-instr-number">
            <InputInstructions allow={dirty} inForm={false} />
          </div>
        ) : null}
      </div>
    </ElementContainer>
  );
}

// ป้ายค่าเหนือปุ่มเลื่อนชิดขอบเมื่อจะล้นกรอบ slider (Streamlit 1.64 ฟังก์ชัน $ ใน Slider)
function clampThumbValue(root: HTMLElement, thumb: HTMLElement, label: HTMLElement) {
  label.style.left = "";
  label.style.right = "";
  const r = root.getBoundingClientRect(), t = thumb.getBoundingClientRect(), a = label.getBoundingClientRect();
  const half = t.width / 2, center = t.left + half;
  if (Math.round(center - a.width / 2) < Math.round(r.left)) label.style.left = `${r.left - center + half}px`;
  else if (Math.round(center + a.width / 2) > Math.round(r.right)) label.style.right = `${center + half - r.right}px`;
}

// st.slider แบบ Streamlit 1.64: กลุ่ม (padding ข้างละครึ่งปุ่ม) > ราง (padding บนล่าง 20px) > แถบสี + ปุ่ม + ป้ายค่า + tick bar
// input range ของเบราว์เซอร์วางทับทั้งกลุ่มแบบโปร่งใส (ตำแหน่งค่าตรงกับปุ่มที่วาด) รับเมาส์/คีย์บอร์ด
function SliderEl({ n }: { n: Of<"slider"> }) {
  const commit = useCommit(n.id);
  const { busy } = useContext(RenderContext);
  const [v, setV] = useState(n.value);
  const rootRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);
  const valueRef = useRef<HTMLDivElement>(null);
  useEffect(() => setV(n.value), [n.value, n.id]);
  const done = () => v !== n.value && commit(v);
  const fmt = (x: number) => formatNumber(x, n.format ?? (n.int ? "%d" : "%0.2f"), n.int);
  const pct = ((v - n.min) / (n.max - n.min || 1)) * 100;
  const disabled = n.disabled || busy;
  useLayoutEffect(() => {
    if (rootRef.current && thumbRef.current && valueRef.current) {
      clampThumbValue(rootRef.current, thumbRef.current, valueRef.current);
    }
  });
  return (
    <ElementContainer wkey={keyOf(n.id)}>
      <div>
        <div ref={rootRef} className="stSlider" data-testid="stSlider">
          <Label text={n.label} help={n.help} visibility={n.label_visibility} />
          <div role="group" aria-label={n.label} className="tfp-slider" data-orientation="horizontal">
            <div className="tfp-slider-track" data-orientation="horizontal">
              <div className={`tfp-slider-fill${disabled ? " tfp-disabled" : ""}`}
                   style={disabled ? undefined : { background: `linear-gradient(to right, var(--st-active) 0%, var(--st-primary) 0%, var(--st-primary) ${pct}%, var(--st-active) ${pct}%)` }} />
              <div ref={thumbRef} className={`tfp-slider-thumb${disabled ? " tfp-disabled" : ""}`} style={{ left: `${pct}%` }}>
                <div ref={valueRef} data-testid="stSliderThumbValue" className="tfp-thumb-value">
                  <Markdown body={fmt(v)} allowHtml={false} />
                </div>
              </div>
              <div data-testid="stSliderTickBar" className="tfp-tickbar">
                <Markdown body={fmt(n.min)} allowHtml={false} />
                <Markdown body={fmt(n.max)} allowHtml={false} />
              </div>
            </div>
            <input type="range" className="tfp-slider-input" aria-label={n.label} min={n.min} max={n.max} step={n.step}
                   value={v} disabled={disabled} onChange={(e) => setV(Number(e.target.value))}
                   onPointerUp={done} onKeyUp={done} onBlur={done} />
          </div>
        </div>
      </div>
    </ElementContainer>
  );
}

// react-aria VisuallyHidden (Streamlit ซ่อน input ของ switch แบบนี้)
const VISUALLY_HIDDEN = {
  border: 0, clip: "rect(0px, 0px, 0px, 0px)", clipPath: "inset(50%)", height: 1, margin: -1, overflow: "hidden",
  padding: 0, position: "absolute", width: 1, whiteSpace: "nowrap",
} as const;
// LabelVisibilityOptions ของ Streamlit: VISIBLE=0, HIDDEN=1, COLLAPSED=2 (เป็น attribute visibility บน stWidgetLabel)
const LABEL_VISIBILITY: Record<string, string> = { visible: "0", hidden: "1", collapsed: "2" };

// st.toggle แบบ Streamlit 1.64: div.stCheckbox > label > (input ซ่อน, แทร็ก+ปุ่ม, stWidgetLabel)
// ป้ายชื่ออยู่ใน DOM เสมอแม้ label_visibility="collapsed" (CSS ของหน้าเดิมอาศัยโครงนี้)
function ToggleEl({ n }: { n: Of<"toggle"> }) {
  const commit = useCommit(n.id);
  const { busy } = useContext(RenderContext);
  const disabled = n.disabled || busy;
  return (
    <ElementContainer wkey={keyOf(n.id)} width="fit-content">
      <div className="row-widget stCheckbox" data-testid="stCheckbox">
        <label className={`tfp-toggle${disabled ? " tfp-disabled" : ""}`}>
          <span style={VISUALLY_HIDDEN}>
            <input aria-label={n.label} type="checkbox" role="switch" title="" checked={n.value} disabled={disabled}
                   onChange={(e) => commit(e.target.checked)} />
          </span>
          <div className={`tfp-switch${n.value ? " on" : ""}`}><div /></div>
          <div data-testid="stWidgetLabel" className="tfp-toggle-label"
               {...({ visibility: LABEL_VISIBILITY[n.label_visibility] ?? "0" } as Record<string, string>)}>
            <div title={n.label} className="tfp-toggle-title">
              <span style={{ display: "contents" }}><Markdown body={n.label} allowHtml={false} /></span>
            </div>
          </div>
        </label>
      </div>
    </ElementContainer>
  );
}

function textAreaHeight(height: number | null | undefined, visibility: string): string {
  const collapsed = visibility === "collapsed";
  const px = (height ?? (collapsed ? 94 : 122)) - (collapsed ? 2 : 30);
  return `${Math.max(0, px)}px`;
}

// ข้อความแนะนำใต้ช่องกรอกแบบ Streamlit 1.64 (InputInstructions.*.js ใน TextInput/TextArea/NumberInput): มีเมื่อช่องมี focus
// และ widget กว้างเกิน 11.25rem — นอกฟอร์มมีข้อความเมื่อพิมพ์แล้วยังไม่ใช้ค่า (dirty) ในฟอร์มเมื่อปุ่ม submit แรกกดได้
// (หน้าเดิมไม่ใช้ max_chars จึงไม่มีตัวนับ) วัดตำแหน่งจากแอปทดสอบ: private/verification/step6-input-instructions/
const IS_MAC = /Mac/i.test(navigator.platform);

function InputInstructions({ allow, inForm, multiline }: { allow: boolean; inForm: boolean; multiline?: boolean }) {
  const action = inForm ? "submit form" : "apply";
  const text = !allow ? null : multiline ? `Press ${IS_MAC ? "⌘" : "Ctrl"}+Enter to ${action}` : `Press Enter to ${action}`;
  return <div data-testid="InputInstructions" className="tfp-instructions">{text ? <span>{text}</span> : null}</div>;
}

function wideWidget(e: { currentTarget: HTMLElement }): boolean {
  const w = e.currentTarget.closest('[data-testid="stElementContainer"]');
  return !!w && w.getBoundingClientRect().width > 180;
}

function TextEl({ n }: { n: Of<"text_input"> | Of<"text_area"> }) {
  const commit = useCommit(n.id);
  const form = useContext(FormContext);
  const { busy } = useContext(RenderContext);
  const inputId = useId();
  const [text, setText] = useState(n.value);
  const [shown, setShown] = useState(false); // ปุ่มแสดง/ซ่อนรหัสผ่านแบบ Streamlit
  const [focused, setFocused] = useState(false); // มี focus และ widget กว้างพอแสดงข้อความแนะนำ
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    setText(n.value);
    setDirty(false);
  }, [n.value, n.id]);
  const change = (s: string) => {
    setText(s);
    setDirty(true);
    if (form) form.set(n.id, s);
  };
  const done = () => {
    setDirty(false);
    if (!form && text !== n.value) commit(text);
  };
  const blur = () => {
    setFocused(false);
    done();
  };
  const allow = form ? form.canSubmit : dirty;
  const isArea = n.type === "text_area";
  const isPassword = !isArea && n.input_type === "password";
  const common = {
    id: inputId,
    "aria-label": n.label,
    value: text,
    placeholder: n.placeholder ?? "",
    maxLength: n.max_chars ?? 10000,
    disabled: n.disabled || busy,
    autoComplete: isPassword ? (n.autocomplete ?? "new-password") : (n.autocomplete ?? ""),
  };
  return (
    <ElementContainer wkey={keyOf(n.id)}>
      <div className={isArea ? "stTextArea" : "stTextInput"} data-testid={isArea ? "stTextArea" : "stTextInput"}>
        <Label text={n.label} help={n.help} visibility={n.label_visibility} htmlFor={inputId} />
        {isArea ? (
          // Streamlit 1.64 TextArea: stTextAreaRootElement > textarea (rows 3) สูง = ความสูงของ widget (ค่าเริ่มต้น 122px หรือ 94px
          // เมื่อซ่อนป้าย) − 30px (หรือ − 2px เมื่อซ่อนป้าย) = 92px; ใช้ค่าด้วย Ctrl/⌘+Enter หรือเมื่อออกจากช่อง
          <div data-testid="stTextAreaRootElement">
            <textarea {...common} rows={3} style={{ height: textAreaHeight(n.height, n.label_visibility) }}
                      onChange={(e) => change(e.target.value)} onFocus={(e) => setFocused(wideWidget(e))} onBlur={blur}
                      onKeyDown={(e) => {
                        if (e.key !== "Enter" || e.nativeEvent.isComposing || !(e.metaKey || e.ctrlKey)) return;
                        e.preventDefault();
                        if (form) form.submit();
                        else done();
                      }} />
          </div>
        ) : (
          // โครงแบบ Streamlit 1.64: react-aria-TextField > stTextInputRootElement > input + กล่องไอคอน
          <div className="react-aria-TextField">
            <div data-testid="stTextInputRootElement" className="tfp-field">
              <input {...common} type={isPassword && !shown ? "password" : "text"} data-testid="stTextInputField"
                     onChange={(e) => change(e.target.value)} onFocus={(e) => setFocused(wideWidget(e))} onBlur={blur}
                     onKeyDown={(e) => {
                       if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
                       if (form) form.submit();
                       else done();
                     }} />
              <div className="tfp-input-icons">
                {isPassword ? (
                  <button type="button" className="tfp-pw-toggle" aria-label={shown ? "Hide password" : "Show password"}
                          aria-pressed={shown} onClick={() => setShown((v) => !v)}>
                    <span className="tfp-icon-wrap">
                      <span data-testid="stIconMaterial" className="material-symbols-rounded" translate="no">
                        {shown ? "visibility_off" : "visibility"}
                      </span>
                    </span>
                  </button>
                ) : null}
              </div>
            </div>
          </div>
        )}
        {/* text_area ไม่มีกล่องห่อ (ตำแหน่งอิงกล่อง element); text_input มีกล่องห่อชิดขอบล่างของ widget เว้นที่ปุ่มแสดงรหัสผ่าน
            (TextInput eqy66r58: sm + iconSizes.base + sm) */}
        {focused && isArea ? <InputInstructions allow={allow} inForm={!!form} multiline /> : null}
        {focused && !isArea ? (
          <div className="tfp-instr-wrap" style={isPassword ? { right: "calc(0.5rem + 1rem + 0.5rem)" } : undefined}>
            <InputInstructions allow={allow} inForm={!!form} />
          </div>
        ) : null}
      </div>
    </ElementContainer>
  );
}

// st.dataframe: Streamlit 1.64 วาดด้วย canvas (Glide Data Grid) — ตาราง HTML นี้ใช้ขนาดคอลัมน์ตามกติกาเดียวกัน (DataFrame.*.js
// Oo/ko/Mu/wg): วัดข้อความด้วยฟอนต์ธีม 400 14px + bodyFont (canvas ไม่โดน CSS ฟอนต์ของหน้าเดิม) กว้าง = ceil(ข้อความยาวสุด + 16)
// จำกัด 50–500 px (minColumnWidth 3.125rem, maxColumnAutoWidth 31.25rem) — วัดบรรทัดแรกของ 10 แถวแรก (เกิน 10 แถว: 9 แถวแรก +
// แถวสุดท้าย) ถ้าเกิน 5 ค่าไม่นับค่าที่ ≥ 2 เท่าของค่าเฉลี่ย และหัวคอลัมน์; use_container_width: คอลัมน์ที่ไม่ใช่ index ได้ grow 1
// พื้นที่ที่เหลือแบ่งเท่ากันปัดลง คอลัมน์สุดท้ายได้เศษ กว้างรวมเกินกล่องจะเลื่อนแนวนอน (ตรวจกับแอปจำลอง: step6-dataframe)
const GLIDE_FONT = '400 14px "Source Sans", sans-serif';
const GLIDE_PAD = 8;

function glideSample<T>(rows: T[]): T[] {
  return rows.length > 10 ? [...rows.slice(0, 9), rows[rows.length - 1]] : rows;
}

function glideColumnWidth(ctx: CanvasRenderingContext2D, title: string, texts: string[]): number {
  const sizes = texts.map((t) => ctx.measureText(t.split("\n", 1)[0]).width + GLIDE_PAD * 2);
  const avg = sizes.reduce((a, b) => a + b, 0) / sizes.length;
  const kept = sizes.length > 5 ? sizes.filter((w) => w < avg * 2) : sizes;
  const widest = Math.max(0, ...kept, ctx.measureText(title).width + GLIDE_PAD * 2);
  return Math.max(50, Math.min(500, Math.ceil(widest)));
}

function cellText(v: unknown): string {
  return v === null ? "None" : String(v);
}

function DataFrameEl({ n }: { n: Of<"dataframe"> }) {
  const box = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(0);
  const [fontLoaded, setFontLoaded] = useState(false);
  useEffect(() => {
    let alive = true;
    document.fonts.load(GLIDE_FONT).catch(() => undefined).finally(() => alive && setFontLoaded(true));
    return () => {
      alive = false;
    };
  }, []);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const update = () => setAvail(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // วัดใหม่เมื่อฟอนต์โหลดเสร็จ (fontLoaded) — ก่อนนั้น canvas ใช้ฟอนต์สำรอง
  const natural = useMemo(() => {
    const ctx = document.createElement("canvas").getContext("2d");
    if (!ctx) return null;
    ctx.font = GLIDE_FONT;
    const rows = glideSample(n.rows);
    return {
      index: n.index ? [glideColumnWidth(ctx, "", glideSample(n.index).map((v) => cellText(v ?? "")))] : [],
      columns: n.columns.map((c, j) => glideColumnWidth(ctx, c, rows.map((r) => cellText(r[j])))),
    };
  }, [n.columns, n.rows, n.index, fontLoaded]);
  let widths: number[] | null = null;
  if (natural) {
    const cols = [...natural.columns];
    const extra = avail - [...natural.index, ...cols].reduce((a, b) => a + b, 0);
    if (n.use_container_width && extra > 0 && cols.length) {
      let left = extra;
      cols.forEach((w, j) => {
        const add = j === cols.length - 1 ? left : Math.min(left, Math.floor(extra / cols.length));
        cols[j] = w + add;
        left -= add;
      });
    }
    widths = [...natural.index, ...cols];
  }
  // ความสูงแบบ Streamlit 1.64 (วัดจากแอปจำลอง): แถว/หัว 35px — สูงไม่ถึงเพดาน: กรอบ = ตาราง + 2 และพื้นที่ Glide = ตาราง + 2
  // (ยื่นทับขอบล่างและเลยกรอบ 1px); ตารางยาว: กรอบ 400 พื้นที่ Glide 398 เลื่อนแนวตั้ง
  const tableHeight = 35 * (n.rows.length + 1);
  return (
    <ElementContainer>
      <div className={`stDataFrame tfp-dataframe${n.use_container_width ? " tfp-stretch" : ""}`} data-testid="stDataFrame">
        <div className="tfp-df-frame" data-testid="stDataFrameResizable" style={{ height: Math.min(tableHeight, 398) + 2 }}>
          <div ref={box} className="tfp-df-scroll" style={{ height: Math.min(tableHeight + 2, 398) }}>
            <table style={widths ? { width: widths.reduce((a, b) => a + b, 0) } : undefined}>
              {widths ? <colgroup>{widths.map((w, i) => <col key={i} style={{ width: w }} />)}</colgroup> : null}
              <thead>
                <tr>{n.index ? <th /> : null}{n.columns.map((c, i) => <th key={i}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {n.rows.map((r, i) => (
                  <tr key={i}>
                    {n.index ? <th>{cellText(n.index[i] ?? "")}</th> : null}
                    {/* Glide จัดตัวเลขชิดขวา ข้อความชิดซ้าย */}
                    {r.map((v, j) => <td key={j} className={typeof v === "number" ? "tfp-num" : undefined}
                                         title={v === null ? undefined : String(v)}>{cellText(v)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </ElementContainer>
  );
}

// ===================== กล่อง =====================
// key ของลูกแบบ Streamlit 1.64 (index.*.js rh.getCurrentKey/visitBlockNode/visitElementNode): block ที่มี id
// (st.container/st.expander ที่ใส่ key — layouts.py; st.form ไม่มี) และ element ที่มี id (widget) ใช้ id เป็น key
// ส่วนอื่นใช้ลำดับ — สถานะฝั่งเบราว์เซอร์ (expander ที่เปิดอยู่ ฯลฯ) จึงอยู่ต่อเมื่อ element ก่อนหน้าเพิ่ม/หายหลัง rerun
// (เดิมใช้ลำดับอย่างเดียว expander "ปรับตัวแปรในสมการ" ปิดเองหลังกดยืนยัน ต่างจากต้นฉบับ)
export function nodeKey(n: Element, i: number): string {
  const id = (n as { id?: unknown }).id;
  if (typeof id === "string" && id) return `w:${id}`;
  const key = (n as { key?: unknown }).key;
  if ((n.type === "container" || n.type === "expander") && typeof key === "string" && key) return `b:${key}`;
  return String(i);
}

// fill: บล็อกในคอลัมน์/ฟอร์ม/expander ของ Streamlit 1.64 สูง 100% (บล็อกระดับหน้าและ st.container สูง auto)
export function VerticalBlock({ items, wkey, border, extra, fill }: { items: Element[]; wkey?: string | null;
                                                                        border?: boolean; extra?: string; fill?: boolean }) {
  return (
    <div className={`stVerticalBlock${keyClass(wkey)}${border ? " tfp-border" : ""}${fill ? " tfp-fill" : ""}${extra ? " " + extra : ""}`}
         data-testid="stVerticalBlock">
      {items.map((c, i) => <Node key={nodeKey(c, i)} n={c} />)}
    </div>
  );
}

// Streamlit 1.64: แถว align-items: stretch เสมอ; การจัดแนวตั้งทำที่คอลัมน์ (margin auto) ไม่ใช่ที่แถว
function ColumnsEl({ n }: { n: Of<"columns"> }) {
  const gap = { small: "1rem", medium: "2rem", large: "4rem" }[n.gap] ?? "1rem";
  return (
    <div data-testid="stLayoutWrapper">
      <div className="stHorizontalBlock" data-testid="stHorizontalBlock" style={{ gap }}>
        {n.children.map((col, i) => {
          const basis = `calc(${col.weight * 100}% - ${gap})`;
          return (
            <div key={i} className={`stColumn tfp-col-valign-${n.vertical_alignment}`} data-testid="stColumn"
                 style={{ width: basis, flex: `1 1 ${basis}` }}>
              <VerticalBlock items={col.children} fill />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ExpanderEl({ n }: { n: Of<"expander"> }) {
  const [open, setOpen] = useState(n.expanded);
  return (
    <div data-testid="stLayoutWrapper">
      <div className={`stExpander${keyClass(n.key)}`} data-testid="stExpander">
        <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
          <summary>
            <span>
              <span><span data-testid="stIconMaterial" className="material-symbols-rounded tfp-exp-icon">
                {open ? "keyboard_arrow_down" : "keyboard_arrow_right"}</span></span>
              <div><Markdown body={n.label} allowHtml={false} /></div>
            </span>
          </summary>
          {/* Streamlit 1.64 ใส่เนื้อหาไว้ใน DOM เสมอ (ปิดอยู่ = inert) */}
          <div data-testid="stExpanderDetails" inert={!open}>
            <VerticalBlock items={n.children} fill />
          </div>
        </details>
      </div>
    </div>
  );
}

function FormEl({ n }: { n: Of<"form"> }) {
  const values = useRef<Record<string, Value>>({});
  useEffect(() => {
    values.current = {}; // ได้หน้าใหม่จาก server แล้ว ล้างค่าที่พิมพ์ค้าง (รหัสผ่านไม่ถูกส่งซ้ำโดยไม่ตั้งใจ)
  }, [n]);
  const { send, busy } = useContext(RenderContext);
  const submitter = firstSubmitter(n.children);
  const state: FormState = {
    id: n.form_id,
    values: () => values.current,
    set: (id, v) => {
      values.current[id] = v;
    },
    submit: () => {
      if (submitter && !submitter.disabled && !busy) send({ trigger: submitter.id, values: values.current });
    },
    canSubmit: !!submitter && !submitter.disabled,
  };
  return (
    <div data-testid="stLayoutWrapper">
      {/* Streamlit 1.64 ใช้ div (ไม่ใช่ <form>) — CSS ของหน้าเดิมอ้าง div[data-testid="stForm"] */}
      <div className="stForm" data-testid="stForm" style={n.border ? undefined : { border: "none", padding: 0 }}>
        <FormContext.Provider value={state}>
          <VerticalBlock items={n.children} fill />
        </FormContext.Provider>
      </div>
    </div>
  );
}

function firstSubmitter(items: Element[]): Of<"button"> | null {
  for (const c of items) {
    if (c.type === "button" && c.is_form_submitter) return c;
    const groups: Element[][] = c.type === "columns" ? c.children.map((col) => col.children)
      : "children" in c ? [c.children as Element[]] : [];
    for (const g of groups) {
      const found = firstSubmitter(g);
      if (found) return found;
    }
  }
  return null;
}

function SpinnerEl({ n }: { n: Of<"spinner"> }) {
  return (
    <ElementContainer>
      <div className="stSpinner" data-testid="stSpinner">
        <div className="tfp-spinner"><i /><Markdown body={n.text} allowHtml={false} /></div>
      </div>
    </ElementContainer>
  );
}

function ExceptionEl({ n }: { n: Of<"exception"> }) {
  return (
    <ElementContainer>
      <div className="stAlert" data-testid="stAlert">
        <div role="alert" data-testid="stAlertContainer" className="stAlertContainer tfp-alert-error">
          <div data-testid="stAlertContentError">
            <div>เกิดข้อผิดพลาดระหว่างแสดงหน้านี้ กรุณาลองใหม่หรือแจ้งผู้ดูแลระบบ (รหัสอ้างอิง {n.ref})</div>
          </div>
        </div>
      </div>
    </ElementContainer>
  );
}

export function Node({ n }: { n: Element }) {
  switch (n.type) {
    case "markdown": return <MarkdownEl n={n} />;
    case "alert": return <AlertEl n={n} />;
    case "button": return <ButtonEl n={n} />;
    case "download_button": return <DownloadEl n={n} />;
    case "selectbox": return <SelectboxEl n={n} />;
    case "multiselect": return <MultiselectEl n={n} />;
    case "number_input": return <NumberInputEl n={n} />;
    case "slider": return <SliderEl n={n} />;
    case "toggle": return <ToggleEl n={n} />;
    case "text_input": return <TextEl n={n} />;
    case "text_area": return <TextEl n={n} />;
    case "vega_lite_chart":
      return (
        <ElementContainer>
          <VegaChart spec={n.spec} theme={n.theme} useContainerWidth={n.use_container_width} />
        </ElementContainer>
      );
    case "dataframe": return <DataFrameEl n={n} />;
    case "spinner": return <SpinnerEl n={n} />;
    case "exception": return <ExceptionEl n={n} />;
    case "container":
      return (
        <div data-testid="stLayoutWrapper">
          <VerticalBlock items={n.children} wkey={n.key} border={n.border} />
        </div>
      );
    case "columns": return <ColumnsEl n={n} />;
    case "expander": return <ExpanderEl n={n} />;
    case "form": return <FormEl n={n} />;
  }
}
