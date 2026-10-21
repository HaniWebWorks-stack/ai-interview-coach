import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built app goes to ../viewer/app and is served by agent/viewer_server.py.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../viewer/app", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
