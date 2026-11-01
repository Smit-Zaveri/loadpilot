import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

const PORT = 8099;
// A fresh database per run keeps tests away from the real history in ~/.loadpilot.
const DB = join(tmpdir(), `loadpilot-e2e-${process.pid}.db`);

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
    command: `uv run --no-sync python -m loadpilot ui --port ${PORT} --db "${DB}"`,
    cwd: "../backend",
    url: `http://127.0.0.1:${PORT}/api/health`,
    // Always start fresh: a reused server would share another run's database.
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
