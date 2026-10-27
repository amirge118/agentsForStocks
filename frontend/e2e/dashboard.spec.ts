import { expect, test, type Page, type Route } from "@playwright/test"

import { agentResults, llmCalls, llmProviders, llmUsage, overview, priceHistory, recommendation, runs } from "../src/test/fixtures"

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
  await page.route(`${API}/symbols/*/prices**`, (route) => json(route, priceHistory))
  await page.route(`${API}/symbols/AAPL/results**`, (route) => {
    const agent = new URL(route.request().url()).searchParams.get("agent")
    return json(route, agent ? agentResults.filter((r) => r.agent_type === agent) : agentResults)
  })
  await page.route(`${API}/symbols/MSFT/results**`, (route) => json(route, []))
  await page.route(`${API}/agents`, (route) => json(route, []))
  // Registered after /runs** so it takes precedence for a run's LLM calls
  await page.route(`${API}/runs/*/llm-calls`, (route) => json(route, llmCalls))
  await page.route(`${API}/llm/usage**`, (route) => json(route, llmUsage))
  await page.route(`${API}/llm/providers`, (route) => json(route, llmProviders))
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

test("symbol page shows the verdict, the charts and one panel per analyst", async ({ page }) => {
  await mockApi(page)
  await page.goto("/symbols/AAPL")

  await expect(page.getByLabel("Recommendation: BUY")).toBeVisible()
  await expect(page.getByRole("meter", { name: "Weighted score" })).toHaveAttribute("aria-valuenow", "42.5")
  await expect(page.getByRole("img", { name: "1 bullish, 0 neutral, 1 bearish" })).toBeVisible()
  await expect(page.getByRole("img", { name: /^Contributions: moat \+12\.0, risk -6\.0/ })).toBeVisible()
  await expect(page.getByTestId("price-chart").locator("canvas").first()).toBeVisible()
  await expect(page.getByText("$235.00")).toBeVisible()
  await expect(page.getByRole("article", { name: "valuation analysis" })).toContainText("+12.00%")
  await expect(page.getByRole("img", { name: /^Score from -20\.0/ })).toBeVisible()

  await page.getByRole("button", { name: "1Y" }).click()
  await expect(page).toHaveURL(/\/symbols\/AAPL\?range=1Y$/)
  await expect(page.getByRole("button", { name: "1Y" })).toHaveAttribute("aria-pressed", "true")
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
  const providers = page.getByRole("list", { name: "Model providers" })
  await expect(providers.getByRole("listitem", { name: "gemini" })).toContainText("chain #1")
})
