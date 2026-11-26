// Vite config. In development the React app runs on :5173 and proxies /api to the FastAPI backend on
// :8000, so the browser only talks to one origin.
//
// `vite build --mode static` builds the public demo instead: relative asset paths, the exported
// SYNTHETIC inbox from static-demo/ copied in, and no API (actions run in the browser only).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === "static" ? "./" : "/",
  publicDir: mode === "static" ? "static-demo" : "public",
  build: { outDir: mode === "static" ? "dist-static" : "dist" },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
}));
