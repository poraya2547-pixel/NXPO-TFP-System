import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// dev: ส่งคำขอ /api ไป API ที่รัน local (compose หรือ uvicorn) — production เสิร์ฟผ่าน nginx (deploy/web.conf)
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.TFP_API_URL ?? "http://127.0.0.1:8000" } },
  build: { sourcemap: false, chunkSizeWarningLimit: 2000 },
  test: { environment: "jsdom" },
});
