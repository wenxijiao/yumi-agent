import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

// All core HTTP API paths live at the server root and are the public contract,
// so the SPA is served under /app instead. In dev we proxy these to the running
// `yumi --server` (default http://127.0.0.1:8000).
const API_PREFIXES = [
  "/chat",
  "/clear",
  "/health",
  "/memory",
  "/config",
  "/tools",
  "/monitor",
  "/stats",
  "/stt",
  "/tts",
  "/timers",
  "/timer-events",
  "/uploads",
]

const target = process.env.YUMI_SERVER_URL || "http://127.0.0.1:8000"

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    // Built assets are shipped inside the Python package and served by FastAPI.
    outDir: path.resolve(__dirname, "../static"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [p, { target, changeOrigin: true }]),
    ),
  },
})
