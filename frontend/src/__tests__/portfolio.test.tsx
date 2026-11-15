import { fireEvent, screen, waitFor, within } from "@testing-library/react"

import { AgentsOnPortfolio } from "@/components/features/portfolio/agents-on-portfolio"
import { HoldingsTable, sortRows, todayPct } from "@/components/features/portfolio/holdings-table"
import { PerformanceChart } from "@/components/features/portfolio/performance-chart"
import { PortfolioSummary } from "@/components/features/portfolio/portfolio-summary"
import { RiskSummary } from "@/components/features/portfolio/risk-summary"
import { parseTargets, SectorWeights } from "@/components/features/portfolio/sector-weights"
import { TransactionForm } from "@/components/features/portfolio/transaction-form"
import { cashEffect, TransactionsTable } from "@/components/features/portfolio/transactions-table"
import { sessionMovers, WeeklyMovers } from "@/components/features/portfolio/weekly-movers"
import { ApiError } from "@/lib/api/client"
import type { PortfolioRepository, SymbolRepository } from "@/lib/api/repositories"
import { exposure, msftPosition, overview, performance, portfolio, transactions } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"
import type { Portfolio, TransactionIn } from "@/types/api"

function portfolioRepo(overrides: Partial<PortfolioRepository> = {}): PortfolioRepository {
  return {
    get: async () => portfolio,
    getPerformance: async () => performance,
    getExposure: async () => exposure,
    setSectorTargets: jest.fn(async () => []),
    getTransactions: async () => transactions,
    addTransaction: jest.fn(async () => transactions[0]!),
    updateTransaction: jest.fn(),
    deleteTransaction: jest.fn(async () => undefined),
    ...overrides,
  }
}

const symbols: SymbolRepository = {
  getAll: async () => [{ symbol: "MSFT", recommendation: { ...overview[0]!.recommendation!, symbol: "MSFT" } }],
  getRecommendation: jest.fn(),
  getResults: jest.fn(),
  getPrices: jest.fn(),
  getOutcomes: jest.fn(),
}

describe("PortfolioSummary", () => {
  it("shows a skeleton, then an error", async () => {
    const { unmount } = renderWithProviders(<PortfolioSummary />, { portfolio: portfolioRepo({ get: () => pending() }) })
    expect(screen.getByLabelText("Loading the portfolio")).toBeInTheDocument()
    unmount()
    renderWithProviders(<PortfolioSummary />, {
      portfolio: portfolioRepo({ get: () => Promise.reject(new Error("down")) }),
    })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the portfolio: down")
  })

  it("adds up the total, today, the P/L and the cash", async () => {
    renderWithProviders(<PortfolioSummary />, { portfolio: portfolioRepo() })
    const summary = await screen.findByRole("region", { name: "Portfolio summary" })
    expect(within(summary).getByText("$10,199.00")).toBeInTheDocument()
    expect(within(summary).getByText("+$100.00")).toHaveClass("text-ok")
    expect(within(summary).getByText("+0.99%")).toBeInTheDocument()
    expect(within(summary).getByText("+$199.00")).toHaveClass("text-ok")
    expect(within(summary).getByText("+3.98% on cost")).toBeInTheDocument()
    expect(within(summary).getByText("49.0% of the portfolio")).toBeInTheDocument()
    expect(await within(summary).findByText("+$150.00")).toHaveClass("text-ok")
    expect(within(summary).getByText("+1.50%, deposits left out")).toBeInTheDocument()
  })

  it("names the holdings left out for lack of a price", async () => {
    const missing: Portfolio = { ...portfolio, unpriced: ["NEWCO"] }
    renderWithProviders(<PortfolioSummary />, { portfolio: portfolioRepo({ get: async () => missing }) })
    expect(await screen.findByText(/No price for NEWCO/)).toBeInTheDocument()
  })
})

describe("HoldingsTable", () => {
  it("shows each holding with the agents' current call, and cash last", async () => {
    renderWithProviders(<HoldingsTable />, { portfolio: portfolioRepo(), symbols })
    const row = (await screen.findByRole("link", { name: "MSFT" })).closest("tr")!
    expect(within(row).getByText("$5,200.00")).toBeInTheDocument()
    expect(within(row).getByText("52.0%")).toBeInTheDocument()
    expect(within(row).getByText("+1.96%")).toHaveClass("text-ok") // today: 100 on 5,100
    expect(within(row).getByText("+$100.00")).toBeInTheDocument()
    expect(within(row).getByText("+3.98%")).toBeInTheDocument()
    expect(within(row).getByText("+$199.00")).toBeInTheDocument()
    // In the Agents column, and under the symbol for a phone (CSS shows one of them)
    expect(await within(row).findAllByText("BUY")).toHaveLength(2)
    const rows = screen.getAllByRole("row")
    expect(rows[rows.length - 1]).toHaveTextContent("Cash$4,999.00")
  })

  it("shows dashes, not 0, for a holding without a price, and marks a stale one", async () => {
    const unpriced = { ...msftPosition, symbol: "NEWCO", price: null, price_as_of: null, value: null, unrealised_pnl: null, unrealised_pct: null, day_change: null, weight: null }
    const stale = { ...msftPosition, price_stale: true, day_change: null }
    renderWithProviders(<HoldingsTable />, {
      portfolio: portfolioRepo({ get: async () => ({ ...portfolio, positions: [stale, unpriced] }) }),
      symbols: { ...symbols, getAll: async () => [] },
    })
    const newco = (await screen.findByRole("link", { name: "NEWCO" })).closest("tr")!
    expect(within(newco).getAllByText("—").length).toBeGreaterThanOrEqual(4)
    expect(within(newco).getByText("Not analysed yet")).toBeInTheDocument()
    const msft = screen.getByRole("link", { name: "MSFT" }).closest("tr")!
    expect(within(msft).getByText("Last close Nov 13, 2026")).toHaveClass("text-bad")
  })

  it("sorts by any column, both ways, with cash kept last", async () => {
    const goog = { ...msftPosition, symbol: "GOOG", value: 2000, weight: 20, unrealised_pct: -7.5, day_change: -40 }
    renderWithProviders(<HoldingsTable />, {
      portfolio: portfolioRepo({ get: async () => ({ ...portfolio, positions: [msftPosition, goog] }) }),
      symbols,
    })
    const order = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("a")?.textContent ?? "Cash")
    await screen.findByRole("link", { name: "GOOG" })
    expect(order()).toEqual(["MSFT", "GOOG", "Cash"]) // largest value first
    expect(screen.getByRole("columnheader", { name: /Value/ })).toHaveAttribute("aria-sort", "descending")

    fireEvent.click(screen.getByRole("button", { name: /Symbol/ }))
    expect(order()).toEqual(["GOOG", "MSFT", "Cash"]) // A to Z first
    fireEvent.click(screen.getByRole("button", { name: /P\/L/ }))
    expect(order()).toEqual(["MSFT", "GOOG", "Cash"])
    fireEvent.click(screen.getByRole("button", { name: /P\/L/ }))
    expect(order()).toEqual(["GOOG", "MSFT", "Cash"])
    expect(screen.getByRole("columnheader", { name: /P\/L/ })).toHaveAttribute("aria-sort", "ascending")
  })

  it("puts a holding without the sorted figure last, either way", () => {
    const row = (symbol: string, value: number | null) => ({
      position: { ...msftPosition, symbol, value },
      call: null,
      todayPct: null,
    })
    const rows = [row("A", 1), row("B", null), row("C", 3)]
    expect(sortRows(rows, { key: "value", desc: true }).map((r) => r.position.symbol)).toEqual(["C", "A", "B"])
    expect(sortRows(rows, { key: "value", desc: false }).map((r) => r.position.symbol)).toEqual(["A", "C", "B"])
    expect(sortRows(rows, { key: "agents", desc: true }).map((r) => r.position.symbol)).toEqual(["A", "B", "C"])
    expect(todayPct({ ...msftPosition, value: null })).toBeNull()
  })

  it("explains how to start when nothing is held", async () => {
    renderWithProviders(<HoldingsTable />, {
      portfolio: portfolioRepo({ get: async () => ({ ...portfolio, positions: [] }) }),
      symbols,
    })
    expect(await screen.findByText(/No holdings yet/)).toBeInTheDocument()
  })
})

describe("PerformanceChart", () => {
  it("compares the time-weighted return with the benchmark, and switches range", async () => {
    renderWithProviders(<PerformanceChart />, { portfolio: portfolioRepo() })
    const chart = await screen.findByRole("figure", { name: "Return against the market" })
    expect(within(chart).getByText("+1.99%")).toHaveClass("text-ok")
    expect(within(chart).getByText("+0.80%")).toBeInTheDocument()
    expect(within(chart).getByText(/pts ahead of SPY/)).toBeInTheDocument()
    const month = within(chart).getByRole("button", { name: "1M" })
    fireEvent.click(month)
    expect(month).toHaveAttribute("aria-pressed", "true")
  })

  it("waits for a second session before drawing", async () => {
    const one = { ...performance, series: performance.series.slice(0, 1) }
    renderWithProviders(<PerformanceChart />, { portfolio: portfolioRepo({ getPerformance: async () => one }) })
    expect(await screen.findByText(/two trading sessions \(from Nov 2, 2026\)/)).toBeInTheDocument()
  })

  it("shows the error when the performance can't load", async () => {
    renderWithProviders(<PerformanceChart />, {
      portfolio: portfolioRepo({ getPerformance: () => Promise.reject(new Error("down")) }),
    })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the performance: down")
  })
})

describe("WeeklyMovers", () => {
  it("lists the week's gainers and losers with the agents' call", async () => {
    renderWithProviders(<WeeklyMovers />, { portfolio: portfolioRepo(), symbols })
    const gainers = await screen.findByRole("region", { name: "Gainers" })
    expect(within(gainers).getByRole("link", { name: "MSFT" })).toBeInTheDocument()
    expect(within(gainers).getByText("+$99.00")).toBeInTheDocument()
    expect(await within(gainers).findByText("BUY")).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: "Losers" })).getByText("None.")).toBeInTheDocument()
    expect(screen.getByText("This week, since each came in")).toBeInTheDocument()
  })

  it("names the close the week is measured from", async () => {
    const since = { ...performance, week_start: "2026-11-06" }
    renderWithProviders(<WeeklyMovers />, { portfolio: portfolioRepo({ getPerformance: async () => since }), symbols })
    expect(await screen.findByText("This week, since the close of Nov 6, 2026")).toBeInTheDocument()
  })

  it("shows the last session's moves until the portfolio has a session of its own", async () => {
    const fresh = { ...performance, series: [], gainers: [], losers: [] }
    renderWithProviders(<WeeklyMovers />, { portfolio: portfolioRepo({ getPerformance: async () => fresh }), symbols })
    expect(await screen.findByText(/Last session \(Nov 13, 2026\)/)).toBeInTheDocument()
    const gainers = screen.getByRole("region", { name: "Gainers" })
    expect(within(gainers).getByText("+1.96%")).toBeInTheDocument()
    expect(within(gainers).getByText("+$100.00")).toBeInTheDocument()
  })

  it("works out a session's moves from the day's change", () => {
    expect(sessionMovers([msftPosition])).toEqual([{ symbol: "MSFT", change: 100, change_pct: (100 / 5100) * 100 }])
    expect(sessionMovers([{ ...msftPosition, day_change: null }])).toEqual([])
    expect(sessionMovers([{ ...msftPosition, day_change: 0 }])).toEqual([])
  })
})

describe("SectorWeights", () => {
  it("shows each sector against its target and saves the targets as exact strings", async () => {
    const setSectorTargets = jest.fn(async () => [])
    renderWithProviders(<SectorWeights />, { portfolio: portfolioRepo({ setSectorTargets }) })
    expect(await screen.findByText("Technology")).toBeInTheDocument()
    expect(screen.getByText("+11.0 pts")).toHaveClass("text-bad")
    expect(screen.getByText("-10.0 pts")).toBeInTheDocument()
    expect(screen.getByLabelText("Target for Cash (%)")).toHaveValue("")

    fireEvent.change(screen.getByLabelText("Target for Technology (%)"), { target: { value: "45.5" } })
    fireEvent.change(screen.getByLabelText("Target for Energy (%)"), { target: { value: "" } })
    fireEvent.click(screen.getByRole("button", { name: "Save targets" }))
    await waitFor(() => expect(setSectorTargets).toHaveBeenCalled())
    expect((setSectorTargets.mock.calls[0] as unknown as [unknown])[0]).toEqual([
      { sector: "Technology", target_pct: "45.5" },
    ])
  })

  it("refuses a target outside 0-100 before sending", async () => {
    const setSectorTargets = jest.fn(async () => [])
    renderWithProviders(<SectorWeights />, { portfolio: portfolioRepo({ setSectorTargets }) })
    fireEvent.change(await screen.findByLabelText("Target for Technology (%)"), { target: { value: "120" } })
    fireEvent.click(screen.getByRole("button", { name: "Save targets" }))
    expect(screen.getByRole("alert")).toHaveTextContent("Technology: a percent from 0 to 100.")
    expect(setSectorTargets).not.toHaveBeenCalled()
    expect(parseTargets({ A: "1.234" })).toBe("A: a percent from 0 to 100.")
    expect(parseTargets({ A: " 7 ", B: "" })).toEqual([{ sector: "A", target_pct: "7" }])
  })

  it("waits for something to be held", async () => {
    const cashOnly = { ...exposure, sectors: [exposure.sectors[2]!] }
    renderWithProviders(<SectorWeights />, { portfolio: portfolioRepo({ getExposure: async () => cashOnly }) })
    expect(await screen.findByText(/once the portfolio holds something/)).toBeInTheDocument()
  })
})

describe("RiskSummary", () => {
  it("reads concentration, beta with its coverage, the fall from the high and the pairs", async () => {
    renderWithProviders(<RiskSummary />, { portfolio: portfolioRepo() })
    expect(await screen.findByText("51.0%")).toHaveClass("text-bad") // over 25% in one name
    expect(screen.getByText("0.91")).toBeInTheDocument()
    expect(screen.getByText(/Covers 100.0% of the holdings/)).toBeInTheDocument()
    expect(await screen.findByText(/At a high/)).toBeInTheDocument()
    const pairs = screen.getByRole("region", { name: "Moving together" })
    expect(within(pairs).getByRole("link", { name: "QQQ" })).toBeInTheDocument()
    expect(within(pairs).getByText("0.87")).toBeInTheDocument()
  })

  it("says so when there is no beta and nothing moves together", async () => {
    const quiet = { ...exposure, risk: { ...exposure.risk, beta: null, beta_coverage: 0, together: [] } }
    renderWithProviders(<RiskSummary />, { portfolio: portfolioRepo({ getExposure: async () => quiet }) })
    expect(await screen.findByText("No beta from the risk agent yet")).toBeInTheDocument()
    expect(screen.getByText(/No two holdings move closely together/)).toBeInTheDocument()
  })
})

describe("AgentsOnPortfolio", () => {
  it("weighs the portfolio by call, flags SELL and lists the calls that changed", async () => {
    renderWithProviders(<AgentsOnPortfolio />, { portfolio: portfolioRepo() })
    expect(await screen.findByRole("img", { name: "SELL 51.0%" })).toBeInTheDocument()
    expect(screen.getByText(/The agents rate/)).toHaveTextContent("The agents rate MSFT SELL: 51.0% of the portfolio")
    const changed = screen.getByRole("region", { name: "Calls that changed" })
    expect(within(changed).getByText("HOLD")).toBeInTheDocument()
    expect(within(changed).getByText("Nov 13, 2026")).toBeInTheDocument()
  })

  it("waits for holdings, and shows a load error", async () => {
    const none = { ...exposure, actions: [], changed: [] }
    const { unmount } = renderWithProviders(<AgentsOnPortfolio />, {
      portfolio: portfolioRepo({ getExposure: async () => none }),
    })
    expect(await screen.findByText(/once the portfolio holds something/)).toBeInTheDocument()
    unmount()
    renderWithProviders(<AgentsOnPortfolio />, {
      portfolio: portfolioRepo({ getExposure: () => Promise.reject(new Error("down")) }),
    })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the agents' view: down")
  })
})

describe("TransactionForm", () => {
  it("sends a buy with exact decimal strings and clears the fields", async () => {
    const addTransaction = jest.fn(async () => transactions[0]!)
    renderWithProviders(<TransactionForm />, { portfolio: portfolioRepo({ addTransaction }) })

    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "BUY" } })
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-11-03" } })
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "msft" } })
    fireEvent.change(screen.getByLabelText("Shares"), { target: { value: "0.5" } })
    fireEvent.change(screen.getByLabelText("Price per share"), { target: { value: "520.123456" } })
    fireEvent.change(screen.getByLabelText("Fee"), { target: { value: "1" } })
    fireEvent.click(screen.getByRole("button", { name: "Record buy" }))

    await waitFor(() => expect(addTransaction).toHaveBeenCalled())
    const body = (addTransaction.mock.calls[0] as unknown as [TransactionIn])[0]
    expect(body).toEqual({
      trade_date: "2026-11-03",
      kind: "BUY",
      symbol: "MSFT",
      shares: "0.5",
      price: "520.123456",
      fee: "1",
      amount: null,
      note: null,
    })
    await waitFor(() => expect(screen.getByLabelText("Shares")).toHaveValue(""))
  })

  it("shows only the fields a kind takes", () => {
    renderWithProviders(<TransactionForm />, { portfolio: portfolioRepo() })
    expect(screen.getByLabelText("Amount ($)")).toBeInTheDocument()
    expect(screen.queryByLabelText("Symbol")).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "TRANSFER_IN" } })
    expect(screen.getByLabelText("Cost per share")).toBeInTheDocument()
    expect(screen.queryByLabelText("Fee")).not.toBeInTheDocument()
    expect(screen.getByText(/Spends no cash/)).toBeInTheDocument()
  })

  it("checks formats before sending, and shows the ledger's reason when the API refuses", async () => {
    const addTransaction = jest.fn(async () => {
      throw new ApiError("can't buy 1 MSFT for 500 on 2026-11-03: only 0 cash then — record a deposit first", 422)
    })
    renderWithProviders(<TransactionForm />, { portfolio: portfolioRepo({ addTransaction }) })

    fireEvent.change(screen.getByLabelText("Amount ($)"), { target: { value: "1.1234567" } })
    fireEvent.click(screen.getByRole("button", { name: "Record deposit" }))
    expect(screen.getByRole("alert")).toHaveTextContent("Amount: a number, up to 6 decimals.")
    expect(addTransaction).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "BUY" } })
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "MSFT" } })
    fireEvent.change(screen.getByLabelText("Shares"), { target: { value: "1" } })
    fireEvent.change(screen.getByLabelText("Price per share"), { target: { value: "0" } })
    fireEvent.click(screen.getByRole("button", { name: "Record buy" }))
    expect(screen.getByRole("alert")).toHaveTextContent("Price must be above 0.")

    fireEvent.change(screen.getByLabelText("Price per share"), { target: { value: "500" } })
    fireEvent.click(screen.getByRole("button", { name: "Record buy" }))
    expect(await screen.findByText(/record a deposit first/, { selector: "form [role=alert]" })).toBeInTheDocument()
  })
})

describe("TransactionsTable", () => {
  it("lists entries with their effect on cash, and deletes after a confirm", async () => {
    const deleteTransaction = jest.fn(async () => undefined)
    const confirm = jest.spyOn(window, "confirm").mockReturnValue(true)
    renderWithProviders(<TransactionsTable />, { portfolio: portfolioRepo({ deleteTransaction }) })

    const buy = (await screen.findByText("Buy")).closest("tr")!
    expect(within(buy).getByText("-$5,001.00")).toHaveClass("text-bad")
    expect(within(buy).getByText(/10 × \$500\.00 \+ \$1\.00 fee/)).toBeInTheDocument()
    const deposit = screen.getByText("Deposit").closest("tr")!
    expect(within(deposit).getByText("+$10,000.00")).toHaveClass("text-ok")
    expect(within(deposit).getByText("opening cash")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Delete the deposit of Nov 2, 2026" }))
    await waitFor(() => expect(deleteTransaction).toHaveBeenCalledWith(1))
    confirm.mockRestore()
  })

  it("says so when there is nothing yet", async () => {
    renderWithProviders(<TransactionsTable />, { portfolio: portfolioRepo({ getTransactions: async () => [] }) })
    expect(await screen.findByText("No transactions yet.")).toBeInTheDocument()
  })

  it("works out each kind's cash effect", () => {
    const base = transactions[0]!
    expect(cashEffect({ ...base, kind: "SELL", shares: 2, price: 10, fee: 1 })).toBe(19)
    expect(cashEffect({ ...base, kind: "WITHDRAW", amount: 50 })).toBe(-50)
    expect(cashEffect({ ...base, kind: "DIVIDEND", amount: 4.2 })).toBe(4.2)
    expect(cashEffect({ ...base, kind: "TRANSFER_IN" })).toBeNull()
  })
})
