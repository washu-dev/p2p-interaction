import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` serves on :5173 and proxies /api to FastAPI on :8000.
// Build: emits static files to dist/, which FastAPI serves in production.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
