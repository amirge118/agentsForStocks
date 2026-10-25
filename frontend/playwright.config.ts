import { defineConfig, devices } from "@playwright/test"

const PORT = 3100
// Test-only credentials for the dashboard's Basic auth (production build requires one)
export const E2E_USER = "e2e"
export const E2E_PASSWORD = "e2e-password"

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
    httpCredentials: { username: E2E_USER, password: E2E_PASSWORD },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Runs the same standalone server the Docker image ships, bound to 0.0.0.0 like the
  // container; browser calls to the /api/backend proxy are mocked per test
  webServer: {
    command: `npm run build && HOSTNAME=0.0.0.0 PORT=${PORT} npm start`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      NEXT_TELEMETRY_DISABLED: "1",
      DASHBOARD_USER: E2E_USER,
      DASHBOARD_PASSWORD: E2E_PASSWORD,
    },
  },
})
