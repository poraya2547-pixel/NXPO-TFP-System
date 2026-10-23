import { afterEach, describe, expect, it, vi } from "vitest";
import { getPending, getView, postEvent } from "./client";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("API transport failures", () => {
  it("preserves the csrf token and uses same-origin URLs and no-store", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ csrf_token: "first" }))
      .mockResolvedValueOnce(Response.json({ csrf_token: "second" }));
    vi.stubGlobal("fetch", fetcher);
    await getView();
    await postEvent({ trigger: "fetch" });
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/v1/events", expect.objectContaining({
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": "first" },
    }));
  });
  it.each([200, 403, 502])("recognizes HTML from a gateway (%s) without exposing its body", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>private gateway details</html>", {
      status, headers: { "Content-Type": "text/html; charset=UTF-8" },
    })));
    await expect(getView()).rejects.toMatchObject({ status: 401, message: expect.stringContaining("ยืนยันสิทธิ์") });
  });
  it("detects redirects even when the response is JSON", async () => {
    const response = Response.json({});
    Object.defineProperty(response, "redirected", { value: true });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(getView()).rejects.toMatchObject({ status: 401 });
  });
  it("preserves backend status and reference", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "CSRF rejected", ref: "test-ref" }, { status: 403 })));
    await expect(postEvent({ trigger: "fetch" })).rejects.toMatchObject({ status: 403, message: expect.stringContaining("test-ref") });
  });
  it("explains network failures without retrying a POST", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetcher);
    await expect(postEvent({ trigger: "fetch" })).rejects.toMatchObject({ status: 0, message: expect.stringContaining("ตรวจสถานะ") });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("aborts a stalled request after 90 seconds without retry", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    vi.stubGlobal("fetch", fetcher);
    const check = expect(getPending()).rejects.toMatchObject({ status: 0, message: expect.stringContaining("90") });
    await vi.advanceTimersByTimeAsync(90000);
    await check;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
