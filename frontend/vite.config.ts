import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8089";

export default defineConfig({
  plugins: [react()],
  build: {
    // The Python package serves the built UI.
    outDir: "../backend/loadpilot/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/demo": backend,
      "/ws": { target: backend, ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
