import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { RunPipelineButton } from "@/components/features/dashboard/run-pipeline-button"
import { WatchlistTable } from "@/components/features/dashboard/watchlist-table"
import type { RunRepository, SymbolRepository } from "@/lib/api/repositories"
import { overview, recommendation } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"

function symbols(getAll: SymbolRepository["getAll"]): SymbolRepository {
  return {
    getAll,
    getRecommendation: jest.fn(),
    getResults: jest.fn(),
    getPrices: jest.fn(),
    getOutcomes: jest.fn(),
  }
}

describe("WatchlistTable", () => {
  it("shows skeletons while loading", () => {
    renderWithProviders(<WatchlistTable />, { symbols: symbols(() => pending()) })
    expect(screen.getByLabelText("Loading watchlist")).toBeInTheDocument()
  })

  it("shows the error with a retry button", async () => {
    const getAll = jest
      .fn<ReturnType<SymbolRepository["getAll"]>, []>()
      .mockRejectedValueOnce(new Error("backend down"))
      .mockResolvedValueOnce(overview)
    renderWithProviders(<WatchlistTable />, { symbols: symbols(getAll) })

    expect(await screen.findByRole("alert")).toHaveTextContent("backend down")
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("AAPL")).toBeInTheDocument()
  })

  it("renders recommendations with finance formatting", async () => {
    renderWithProviders(<WatchlistTable />, { symbols: symbols(async () => overview) })

    const link = await screen.findByRole("link", { name: "AAPL" })
    expect(link).toHaveAttribute("href", "/symbols/AAPL")
    expect(screen.getByText("BUY")).toHaveClass("text-ok")
    expect(screen.getByText("+42.5")).toHaveClass("text-ok")
    expect(screen.getByText("72%")).toBeInTheDocument()
    expect(screen.getByText("Oct 23, 2026")).toBeInTheDocument()
    expect(screen.getByText("Not analysed yet")).toBeInTheDocument()
  })

  it("shows the disclaimer once and no compliance marker when the review passed", async () => {
    renderWithProviders(<WatchlistTable />, { symbols: symbols(async () => overview) })

    expect(await screen.findByText(recommendation.disclaimer)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Compliance:/)).not.toBeInTheDocument()
  })

  it("marks rows that need review, with the reasons", async () => {
    const shaky = { ...recommendation, needs_review: ["only 2/8 analysts reported"] }
    renderWithProviders(<WatchlistTable />, {
      symbols: symbols(async () => [{ symbol: "AAPL", recommendation: shaky }]),
    })
    expect(await screen.findByLabelText("Needs review: only 2/8 analysts reported")).toBeInTheDocument()
  })

  it("marks rows whose reasoning was flagged or replaced", async () => {
    const finding = { rule: "promissory_language", severity: "fail" as const, phrase: "guaranteed" }
    const failed = { ...recommendation, compliance: { status: "fail" as const, findings: [finding] } }
    const flagged = { ...recommendation, symbol: "MSFT", compliance: { status: "flag" as const, findings: [] } }
    renderWithProviders(<WatchlistTable />, {
      symbols: symbols(async () => [
        { symbol: "AAPL", recommendation: failed },
        { symbol: "MSFT", recommendation: flagged },
      ]),
    })

    expect(await screen.findByLabelText("Compliance: original reasoning replaced")).toHaveTextContent("Replaced")
    expect(screen.getByLabelText("Compliance: flagged")).toHaveTextContent("Flagged")
    expect(screen.getAllByText(recommendation.disclaimer)).toHaveLength(1)
  })

  it("shows no disclaimer when nothing has been analysed", async () => {
    renderWithProviders(<WatchlistTable />, {
      symbols: symbols(async () => [{ symbol: "MSFT", recommendation: null }]),
    })

    expect(await screen.findByText("Not analysed yet")).toBeInTheDocument()
    expect(screen.queryByText(recommendation.disclaimer)).not.toBeInTheDocument()
  })
})

describe("RunPipelineButton", () => {
  function runs(create: RunRepository["create"]): RunRepository {
    return { getAll: jest.fn(), create }
  }

  it("starts a run, invalidates queries and confirms with a toast", async () => {
    const create = jest.fn().mockResolvedValue({
      pipeline_run_id: "p1", run_date: "2026-10-23", symbols: ["AAPL"], agents: ["a", "b"],
      force: false,
    })
    const { queryClient } = renderWithProviders(<RunPipelineButton symbols={["AAPL"]} />, {
      runs: runs(create),
    })
    const invalidate = jest.spyOn(queryClient, "invalidateQueries")

    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }))

    expect(await screen.findByText("Pipeline started")).toBeInTheDocument()
    expect(screen.getByText("1 symbols · 2 agents")).toBeInTheDocument()
    expect(create).toHaveBeenCalledWith({ symbols: ["AAPL"], agents: null, force: false })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs"] })
  })

  it("shows a destructive toast when the run cannot start", async () => {
    const create = jest.fn().mockRejectedValue(new Error("Unknown agent"))
    renderWithProviders(<RunPipelineButton />, { runs: runs(create) })

    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }))

    expect(await screen.findByText("Could not start pipeline")).toBeInTheDocument()
    expect(screen.getByText("Unknown agent")).toBeInTheDocument()
    await waitFor(() => expect(create).toHaveBeenCalledWith({ symbols: null, agents: null, force: false }))
  })
})
