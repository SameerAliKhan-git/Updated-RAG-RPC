import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://localhost:5174",
    trace: "retain-on-failure",
  },
  // Isolated ports (8001/5174) so E2E can run alongside the real stack
  webServer: [
    {
      command: "uv run python src/run_mock_api.py",
      cwd: "..",
      port: 8001,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { MOCK_API_PORT: "8001" },
    },
    {
      command: "npm run dev -- --port 5174",
      port: 5174,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_TARGET: "http://localhost:8001" },
    },
  ],
});
