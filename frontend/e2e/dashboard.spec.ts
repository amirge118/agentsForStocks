import { expect, test, type Page, type Route } from "@playwright/test"

import { overview, recommendation, runs } from "../src/test/fixtures"

const API = "http://localhost:8000/api/v1"

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*" },
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
  await page.route(`${API}/pipeline/runs`, async (route) => {
    if (route.request().method() === "OPTIONS") return json(route, {})
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
  await page.getByRole("button", { name: "Run analysis" }).click()

  await expect(page.getByText("Pipeline started")).toBeVisible()
  expect(JSON.parse(posted[0] ?? "{}")).toEqual({ symbols: null, agents: null, force: false })
})
