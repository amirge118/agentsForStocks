import { fireEvent, screen, waitFor, within } from "@testing-library/react"

import { HoldingsTable } from "@/components/features/portfolio/holdings-table"
import { PerformanceChart } from "@/components/features/portfolio/performance-chart"
import { PortfolioSummary } from "@/components/features/portfolio/portfolio-summary"
import { TransactionForm } from "@/components/features/portfolio/transaction-form"
import { cashEffect, TransactionsTable } from "@/components/features/portfolio/transactions-table"
import { WeeklyMovers } from "@/components/features/portfolio/weekly-movers"
import { ApiError } from "@/lib/api/client"
import type { PortfolioRepository, SymbolRepository } from "@/lib/api/repositories"
import { msftPosition, overview, performance, portfolio, transactions } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"
import type { Portfolio, TransactionIn } from "@/types/api"

function portfolioRepo(overrides: Partial<PortfolioRepository> = {}): PortfolioRepository {
  return {
    get: async () => portfolio,
    getPerformance: async () => performance,
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
    expect(within(row).getByText("+$100.00")).toHaveClass("font-mono")
    expect(within(row).getByText("+3.98%")).toBeInTheDocument()
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
    expect(await screen.findByText(/second trading session/)).toBeInTheDocument()
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
    expect(screen.getByText("Nothing down this week.")).toBeInTheDocument()
    expect(screen.getByText(/Since each came in this week/)).toBeInTheDocument()
  })

  it("names the close the week is measured from", async () => {
    const since = { ...performance, week_start: "2026-11-06" }
    renderWithProviders(<WeeklyMovers />, { portfolio: portfolioRepo({ getPerformance: async () => since }), symbols })
    expect(await screen.findByText(/Since the close of Nov 6, 2026/)).toBeInTheDocument()
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
