import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { AddSymbolForm } from "@/components/features/dashboard/add-symbol-form"
import { ScoreSparkline } from "@/components/features/dashboard/score-sparkline"
import { WatchlistTable } from "@/components/features/dashboard/watchlist-table"
import { ApiError } from "@/lib/api/client"
import type { SymbolRepository, WatchlistRepository } from "@/lib/api/repositories"
import { agentResults, overview } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

function symbols(over: Partial<SymbolRepository> = {}): SymbolRepository {
  return {
    getAll: async () => overview,
    getRecommendation: jest.fn(),
    getResults: async () => [],
    getPrices: jest.fn(),
    ...over,
  }
}

function watchlist(over: Partial<WatchlistRepository> = {}): WatchlistRepository {
  const item = (symbol: string) => ({ symbol, position: 0, added_at: "2026-10-27T00:00:00Z" })
  return {
    getAll: jest.fn(),
    add: jest.fn(async (symbol: string) => item(symbol)),
    remove: jest.fn(async () => undefined),
    reorder: jest.fn(async (list: string[]) => list.map(item)),
    ...over,
  }
}

describe("AddSymbolForm", () => {
  it("upper-cases the ticker, adds it, clears the input and refreshes the list", async () => {
    const repo = watchlist()
    const { queryClient } = renderWithProviders(<AddSymbolForm />, { watchlist: repo, symbols: symbols() })
    const invalidate = jest.spyOn(queryClient, "invalidateQueries")

    const input = screen.getByLabelText("Ticker symbol")
    await userEvent.type(input, " nvda ")
    await userEvent.click(screen.getByRole("button", { name: "Add" }))

    await waitFor(() => expect(repo.add).toHaveBeenCalledWith("NVDA"))
    expect(await screen.findByText("NVDA added")).toBeInTheDocument()
    expect(input).toHaveValue("")
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["symbols"] })
  })

  it("refuses a malformed ticker without calling the API", async () => {
    const repo = watchlist()
    renderWithProviders(<AddSymbolForm />, { watchlist: repo })

    await userEvent.type(screen.getByLabelText("Ticker symbol"), "BAD$")
    await userEvent.click(screen.getByRole("button", { name: "Add" }))

    expect(screen.getByText("Letters, digits and “.” only, up to 10.")).toBeInTheDocument()
    expect(repo.add).not.toHaveBeenCalled()
  })

  it("shows the backend's reason when the add fails", async () => {
    const repo = watchlist({ add: () => Promise.reject(new ApiError("AAPL is already on the watchlist", 409)) })
    renderWithProviders(<AddSymbolForm />, { watchlist: repo })

    await userEvent.type(screen.getByLabelText("Ticker symbol"), "AAPL")
    await userEvent.click(screen.getByRole("button", { name: "Add" }))

    expect(await screen.findByText("Could not add the symbol")).toBeInTheDocument()
    expect(screen.getByText("AAPL is already on the watchlist")).toBeInTheDocument()
    expect(screen.getByLabelText("Ticker symbol")).toHaveValue("AAPL")
  })
})

describe("WatchlistTable controls", () => {
  it("moves a symbol and disables the moves past either end", async () => {
    const repo = watchlist()
    renderWithProviders(<WatchlistTable />, { symbols: symbols(), watchlist: repo })

    expect(await screen.findByRole("button", { name: "Move AAPL up" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Move MSFT down" })).toBeDisabled()
    await userEvent.click(screen.getByRole("button", { name: "Move AAPL down" }))
    await waitFor(() => expect(repo.reorder).toHaveBeenCalledWith(["MSFT", "AAPL"]))
  })

  it("asks before removing, and Keep cancels", async () => {
    const repo = watchlist()
    renderWithProviders(<WatchlistTable />, { symbols: symbols(), watchlist: repo })

    await userEvent.click(await screen.findByRole("button", { name: "Remove AAPL" }))
    await userEvent.click(screen.getByRole("button", { name: "Keep" }))
    expect(repo.remove).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole("button", { name: "Remove AAPL" }))
    const row = screen.getByRole("row", { name: /AAPL/ })
    await userEvent.click(within(row).getByRole("button", { name: "Remove AAPL" }))
    await waitFor(() => expect(repo.remove).toHaveBeenCalledWith("AAPL"))
  })

  it("toasts when a reorder fails", async () => {
    const repo = watchlist({ reorder: () => Promise.reject(new Error("set mismatch")) })
    renderWithProviders(<WatchlistTable />, { symbols: symbols(), watchlist: repo })

    await userEvent.click(await screen.findByRole("button", { name: "Move MSFT up" }))
    expect(await screen.findByText("Could not reorder the watchlist")).toBeInTheDocument()
  })

  it("explains an empty watchlist", async () => {
    renderWithProviders(<WatchlistTable />, { symbols: symbols({ getAll: async () => [] }) })
    expect(await screen.findByText(/The watchlist is empty/)).toHaveAttribute("role", "status")
  })
})

describe("ScoreSparkline", () => {
  it("summarises the score trend for screen readers", async () => {
    const history = agentResults.filter((r) => r.agent_type === "recommendation")
    renderWithProviders(<ScoreSparkline symbol="AAPL" />, { symbols: symbols({ getResults: async () => history }) })
    expect(await screen.findByRole("img")).toHaveAccessibleName("Score trend over 3 runs: -20.0 to +42.5")
  })

  it("says so when there are fewer than two runs", async () => {
    const one = agentResults.slice(0, 1)
    renderWithProviders(<ScoreSparkline symbol="AAPL" />, { symbols: symbols({ getResults: async () => one }) })
    expect(await screen.findByText("Not enough runs")).toBeInTheDocument()
  })
})
