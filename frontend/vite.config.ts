import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs on :8000; proxying keeps the browser on one origin in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
