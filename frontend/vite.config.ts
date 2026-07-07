import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Dev proxy: when running `npm run dev` on the host, /api/* is forwarded to
// the FastAPI container (host-mapped to 8002). In the production Docker
// build, nginx does the equivalent proxy inside the container.
//
// `base` controls the URL prefix Vite bakes into every asset URL at build
// time. Defaults to `/` (SPA at domain root). Set VITE_BASE=/conv-agent/
// when serving the SPA under a path on a parent domain — API calls made
// via `import.meta.env.BASE_URL + "api"` in the frontend code will then
// naturally hit `/conv-agent/api/*`, which the outer reverse-proxy strips.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8002",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
