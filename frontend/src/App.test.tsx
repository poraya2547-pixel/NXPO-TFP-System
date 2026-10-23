import { act, useContext } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { ApiError, getView, postEvent } from "./api/client";

vi.mock("./api/client", async (original) => ({
  ...await original<typeof import("./api/client")>(),
  getView: vi.fn(), postEvent: vi.fn(), getPending: vi.fn(),
}));
vi.mock("./render/Tree", async () => {
  const { createContext } = await import("react");
  const RenderContext = createContext<any>({});
  return { RenderContext, nodeKey: () => "test", Node: () => {
    const { send, busy } = useContext(RenderContext);
    return <button disabled={busy} onClick={() => send({ trigger: "fetch" })}>Test action</button>;
  } };
});

afterEach(() => { vi.clearAllMocks(); document.body.innerHTML = ""; });

it("keeps the 403 action error after refreshing the session and unlocks the button", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const view = { sidebar: { children: [] }, main: { children: [{}] }, pending: false, csrf_token: "test" };
  vi.mocked(getView).mockResolvedValue(view as any);
  vi.mocked(postEvent).mockRejectedValue(new ApiError(403, "CSRF rejected"));
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  try {
    await act(async () => { root.render(<App />); });
    await act(async () => { host.querySelector("button")!.click(); });
    expect(getView).toHaveBeenCalledTimes(2);
    expect(postEvent).toHaveBeenCalledTimes(1);
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("CSRF rejected");
    expect(host.querySelector("button")!.disabled).toBe(false);
  } finally { await act(async () => { root.unmount(); }); }
});
