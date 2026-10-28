import { defineConfig, devices } from "@playwright/test";

const PORT = 8099;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1, // the server allows one active run at a time
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // Serves the built UI (run `pnpm build` first) plus the API and demo target.
    command: `uv run --no-sync python -m loadpilot ui --port ${PORT}`,
    cwd: "../backend",
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
