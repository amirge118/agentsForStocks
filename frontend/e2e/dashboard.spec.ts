import { expect, test, type Page, type Route } from "@playwright/test"

import {
  agentResults,
  llmCalls,
  llmProviders,
  llmUsage,
  overview,
  priceHistory,
  recommendation,
  runs,
  symbolTrackRecord,
  trackRecord,
} from "../src/test/fixtures"

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
  await page.route(`${API}/outcomes/track-record**`, (route) => json(route, trackRecord))
  await page.route(`${API}/symbols/*/outcomes**`, (route) => json(route, symbolTrackRecord))
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

/** A watchlist that remembers adds, moves and removes; returns the calls it saw. */
async function mockWatchlist(page: Page): Promise<string[]> {
  let list = overview.map((o) => o.symbol)
  const calls: string[] = []
  // Registered after mockApi, so these win for /symbols and /watchlist
  await page.route(`${API}/symbols`, (route) => json(route, list.map((symbol) => ({ symbol, recommendation: null }))))
  await page.route(`${API}/watchlist**`, async (route) => {
    const request = route.request()
    calls.push(`${request.method()} ${new URL(request.url()).pathname}`)
    expect(request.headers()["content-type"]).toBe("application/json")
    if (request.method() === "POST") {
      const { symbol } = request.postDataJSON() as { symbol: string }
      list = [...list, symbol]
      return json(route, { symbol, position: list.length - 1, added_at: "2026-10-27T00:00:00Z" }, 201)
    }
    if (request.method() === "PUT") {
      list = (request.postDataJSON() as { symbols: string[] }).symbols
      return json(route, list.map((symbol, position) => ({ symbol, position, added_at: "2026-10-27T00:00:00Z" })))
    }
    list = list.filter((s) => !request.url().endsWith(`/${s}`))
    return route.fulfill({ status: 204 })
  })
  return calls
}

test("adding, reordering and removing watchlist symbols", async ({ page }) => {
  await mockApi(page)
  const calls = await mockWatchlist(page)
  await page.goto("/")

  await page.getByLabel("Ticker symbol").fill("nvda")
  await page.getByRole("button", { name: "Add", exact: true }).click()
  await expect(page.getByText("NVDA added", { exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "NVDA" })).toBeVisible()

  await page.getByRole("button", { name: "Move NVDA up" }).click()
  await expect(page.locator("tbody tr").nth(1)).toContainText("NVDA")

  await page.getByRole("button", { name: "Remove AAPL" }).click()
  await page.getByRole("row", { name: /AAPL/ }).getByRole("button", { name: "Remove AAPL" }).click()
  await expect(page.getByRole("link", { name: "AAPL" })).toHaveCount(0)
  expect(calls).toEqual(["POST /api/backend/watchlist", "PUT /api/backend/watchlist/order", "DELETE /api/backend/watchlist/AAPL"])
})

test("the analysis reads as a story that ends on the verdict", async ({ page }) => {
  await mockApi(page)
  await page.goto("/symbols/AAPL")
  await page.getByRole("link", { name: "Read it as a story" }).click()

  await expect(page).toHaveURL(/\/symbols\/AAPL\/story$/)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("BUY, SELL or HOLD for AAPL?")
  await expect(page.getByRole("region", { name: /analyst \d of 5/ })).toHaveCount(5)
  const verdict = page.getByRole("region", { name: "The verdict" })
  await verdict.scrollIntoViewIfNeeded()
  await expect(verdict).toContainText("BUY")
  await expect(verdict).toContainText("+42.5")
})

test("track record page and a symbol's past calls", async ({ page }) => {
  await mockApi(page)
  await page.goto("/")
  await page.getByRole("link", { name: "Track record" }).click()
  await expect(page).toHaveURL(/\/track-record$/)
  const table = page.getByRole("table", { name: "Track record" })
  await expect(table).toContainText("recommendation")
  await expect(table).toContainText("+1.23%")
  await expect(page.getByRole("table", { name: "Calibration" })).toBeVisible()

  await page.goto("/symbols/AAPL")
  const calls = page.getByRole("table", { name: "Past recommendations" })
  await expect(calls).toContainText("Sep 22, 2026")
  await expect(calls).toContainText("Wrong")
  await expect(page.getByText(/of 2 calls \(50%\)/)).toBeVisible()
})

test("on a phone, each row's actions are in one menu", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  const calls = await mockWatchlist(page)
  await page.goto("/")

  await expect(page.getByRole("button", { name: "Move MSFT up" })).toBeHidden()
  await page.getByRole("button", { name: "Actions for MSFT" }).click()
  await page.getByRole("menuitem", { name: "Move up" }).click()
  await expect(page.locator("tbody tr").first()).toContainText("MSFT")
  expect(calls).toEqual(["PUT /api/backend/watchlist/order"])
})

test("a row can be dragged into place with the keyboard", async ({ page }) => {
  await mockApi(page)
  const calls = await mockWatchlist(page)
  await page.goto("/")

  const handle = page.getByRole("button", { name: "Reorder AAPL" })
  const announced = page.locator('[id^="DndLiveRegion"]')
  await handle.focus()
  // Each key waits for the drag to take it (the handle is pressed, then the screen reader hears the move)
  await page.keyboard.press("Space")
  await expect(handle).toHaveAttribute("aria-pressed", "true")
  await page.keyboard.press("ArrowDown")
  await expect(announced).toContainText("AAPL is over position 2 of 2.")
  await page.keyboard.press("Space")
  await expect(page.locator("tbody tr").first()).toContainText("MSFT")
  expect(calls).toEqual(["PUT /api/backend/watchlist/order"])
})

test("the story keeps a running score beside the act being read", async ({ page }) => {
  await mockApi(page)
  await page.goto("/symbols/AAPL/story")
  const total = page.getByRole("complementary", { name: "Running score" }).locator("[aria-live]")

  await page.getByRole("region", { name: /^risk,/ }).evaluate((el) => el.scrollIntoView({ block: "center" }))
  await expect(total).toHaveText("-6.0")

  await page.getByRole("region", { name: "The verdict" }).evaluate((el) => el.scrollIntoView({ block: "center" }))
  await expect(total).toHaveText("+6.0")
})
