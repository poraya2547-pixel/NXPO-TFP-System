// เรียก API ของ backend (ชนิดข้อมูลมาจาก OpenAPI: src/api/schema.d.ts — สร้างด้วย npm run gen:api ห้ามแก้มือ)
import type { components } from "./schema";

export type View = components["schemas"]["View"];
export type Element = components["schemas"]["View"]["main"]["children"][number];
export type EventBody = components["schemas"]["Event"];
export type PendingStatus = components["schemas"]["PendingStatus"];

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let csrfToken = "";

async function parse<T>(r: Response): Promise<T> {
  // Access gateways may return a login HTML page after following a redirect.
  if (r.redirected || (r.headers.get("content-type") ?? "").includes("text/html")) {
    throw new ApiError(401, "ไม่ได้รับข้อมูล API: อาจต้องยืนยันสิทธิ์เข้าเว็บอีกครั้ง กรุณาเปิดลิงก์เว็บใหม่และตรวจสถานะก่อนกดซ้ำ");
  }
  if (!r.ok) {
    let msg = `เกิดข้อผิดพลาด (${r.status})`;
    try {
      const body = await r.json();
      if (typeof body?.detail === "string") msg = body.detail;
      if (typeof body?.ref === "string") msg += ` · รหัสอ้างอิง ${body.ref}`;
    } catch {
      // ไม่ใช่ JSON — ใช้ข้อความทั่วไป
    }
    throw new ApiError(r.status, msg);
  }
  return (await r.json()) as T;
}


// Only wait for the HTTP response, not the worker job. Never replay a POST.
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 90000);
  try {
    return await parse<T>(await fetch(path, {
      ...init, credentials: "same-origin", cache: "no-store", signal: controller.signal,
    }));
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (controller.signal.aborted) {
      throw new ApiError(0, "ไม่ได้รับคำตอบจากเซิร์ฟเวอร์ภายใน 90 วินาที งานอาจเริ่มแล้ว กรุณาโหลดหน้าใหม่เพื่อตรวจสถานะก่อนกดซ้ำ");
    }
    throw new ApiError(0, "เชื่อมต่อ API ไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ตและสิทธิ์เข้าเว็บ แล้วโหลดหน้าใหม่เพื่อตรวจสถานะก่อนกดซ้ำ");
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getView(): Promise<View> {
  const v = await request<View>("/api/v1/view");
  csrfToken = v.csrf_token;
  return v;
}

export async function postEvent(body: EventBody): Promise<View> {
  const v = await request<View>("/api/v1/events", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });
  csrfToken = v.csrf_token;
  return v;
}

export async function getPending(): Promise<PendingStatus> {
  return request<PendingStatus>("/api/v1/pending");
}
