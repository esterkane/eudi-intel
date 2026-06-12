import { defineConfig } from "@playwright/test";

// E2E against the live compose stack (run-and-test skill): web on :3000,
// api on :8000. Bring the stack up before running: docker compose up -d
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    // Playwright's bundled chromium fails to launch on this machine
    // (side-by-side configuration error); system Edge is Chromium anyway.
    channel: process.env.E2E_BROWSER_CHANNEL ?? "msedge",
  },
  reporter: [["list"]],
});
