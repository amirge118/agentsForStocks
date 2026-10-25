import { expect, test, type Page, type Route } from "@playwright/test"

import { llmCalls, llmUsage, overview, recommendation, runs } from "../src/test/fixtures"

const API = "**/api/backend"

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

async function mockApi(page: Page): Promise<string[]> {
  const posted: string[] = []
  await page.route(`${API}/symbols`, (route) => json(route, overview))
  await page.route(`${API}/symbols/AAPL/recommendation`, (route) => json(route, recommendation))
  await page.route(`${API}/symbols/MSFT/recommendation`, (route) =>
    json(route, { detail: "No recommendation for MSFT yet" }, 404),
  )
  await page.route(`${API}/runs**`, (route) => json(route, runs))
  // Registered after /runs** so it takes precedence for a run's LLM calls
  await page.route(`${API}/runs/*/llm-calls`, (route) => json(route, llmCalls))
  await page.route(`${API}/llm/usage**`, (route) => json(route, llmUsage))
  await page.route(`${API}/pipeline/runs`, async (route) => {
    posted.push(route.request().postData() ?? "")
    return json(
      route,
      { pipeline_run_id: "p1", run_date: "2026-10-23", symbols: ["AAPL", "MSFT"], agents: ["a"], force: false },
      202,
    )
  })
  return posted
}

test("watchlist links through to the recommendation detail", async ({ page }) => {
  await mockApi(page)
  await page.goto("/")

  await expect(page.getByRole("link", { name: "AAPL" })).toBeVisible()
  await expect(page.getByText("Not analysed yet")).toBeVisible()

  await page.getByRole("link", { name: "AAPL" }).click()
  await expect(page).toHaveURL(/\/symbols\/AAPL$/)
  await expect(page.getByText("Wide moat and accelerating services growth")).toBeVisible()
  await expect(page.getByRole("table", { name: "Agent breakdown" })).toBeVisible()
  await expect(page.getByRole("table", { name: "Agent runs" })).toContainText("provider down")
})

test("symbol without a recommendation explains what to do", async ({ page }) => {
  await mockApi(page)
  await page.goto("/symbols/msft")
  await expect(page.getByRole("status")).toContainText("No recommendation for MSFT yet")
})

test("starting an analysis confirms with a toast", async ({ page }) => {
  const posted = await mockApi(page)
  await page.goto("/")
  // The button is server-rendered: wait for client data (proves React hydrated) before clicking
  await expect(page.getByRole("link", { name: "AAPL" })).toBeVisible()
  await page.getByRole("button", { name: "Run analysis" }).click()

  // Radix also copies toast text into an aria-live announcer, so scope to the visible toast list
  const notifications = page.getByRole("region", { name: /notifications/i })
  await expect(notifications.getByText("Pipeline started")).toBeVisible()
  expect(JSON.parse(posted[0] ?? "{}")).toEqual({ symbols: null, agents: null, force: false })
})

test("dashboard requires the password", async ({ browser, baseURL }) => {
  const anonymous = await browser.newContext({ httpCredentials: undefined })
  const resp = await anonymous.request.get(`${baseURL}/`)
  expect(resp.status()).toBe(401)
  expect(resp.headers()["www-authenticate"]).toContain("Basic")
  const proxied = await anonymous.request.get(`${baseURL}/api/backend/symbols`)
  expect(proxied.status()).toBe(401)  // the backend proxy is protected too
  await anonymous.close()
})

test("token usage page and a run's prompts", async ({ page }) => {
  await mockApi(page)
  await page.goto("/runs")
  await page.getByRole("link", { name: "1,850 / 96" }).click()
  await expect(page).toHaveURL(/\/runs\/r1$/)
  const calls = page.getByRole("list", { name: "LLM calls" })
  await expect(calls).toContainText("claude-haiku-4-5")
  await calls.getByText("System prompt").click()
  await expect(calls.getByText(/five years of financial statements/)).toBeVisible()

  await page.getByRole("link", { name: "Tokens & cost" }).click()
  await expect(page.getByRole("table", { name: "LLM usage" })).toContainText("19,800")
  await expect(page.getByLabel("Totals")).toContainText("$0.0288")
})
