import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the backend so the SPA stays same-origin (secure context
// via http://localhost, D7). Production: FastAPI serves the built SPA.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8740";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/api": backend,
      "/healthz": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
