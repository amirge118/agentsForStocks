import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { TrackRecordTable } from "@/components/features/outcomes/track-record-table"
import { TrackRecordCard } from "@/components/features/stocks/track-record-card"
import type { OutcomeRepository, SymbolRepository } from "@/lib/api/repositories"
import { symbolTrackRecord, trackRecord } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"

function outcomes(overrides: Partial<OutcomeRepository> = {}): OutcomeRepository {
  return { getTrackRecord: jest.fn(async () => trackRecord), ...overrides }
}

function symbols(getOutcomes: SymbolRepository["getOutcomes"]): SymbolRepository {
  return { getAll: jest.fn(), getRecommendation: jest.fn(), getResults: jest.fn(), getOutcomes }
}

describe("TrackRecordTable", () => {
  it("shows a skeleton while loading", () => {
    renderWithProviders(<TrackRecordTable />, {
      outcomes: outcomes({ getTrackRecord: () => pending() }),
    })
    expect(screen.getByLabelText("Loading track record")).toBeInTheDocument()
  })

  it("shows the error", async () => {
    const getTrackRecord = jest.fn(async () => {
      throw new Error("backend down")
    })
    renderWithProviders(<TrackRecordTable />, { outcomes: outcomes({ getTrackRecord }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("backend down")
  })

  it("explains an empty record", async () => {
    const getTrackRecord = jest.fn(async () => ({ ...trackRecord, agents: [] }))
    renderWithProviders(<TrackRecordTable />, { outcomes: outcomes({ getTrackRecord }) })
    expect(await screen.findByText(/No settled calls yet. 4 outcomes are pending/)).toBeInTheDocument()
  })

  it("renders each agent, per signal and per confidence, and switches horizon", async () => {
    const repo = outcomes()
    renderWithProviders(<TrackRecordTable />, { outcomes: repo })

    const table = await screen.findByRole("table", { name: "Track record" })
    const rec = within(table).getByText("recommendation").closest("tr") as HTMLElement
    expect(within(rec).getByText("67%")).toBeInTheDocument()
    expect(within(rec).getByText("+1.23%")).toHaveClass("text-ok")
    expect(within(rec).getByText("100%")).toBeInTheDocument() // bullish, 2 of 2
    const history = within(table).getByText("financial history").closest("tr") as HTMLElement
    expect(within(history).getByText("-0.40%")).toHaveClass("text-bad")

    const calibration = screen.getByRole("table", { name: "Calibration" })
    expect(within(calibration).getByText("80-100%")).toBeInTheDocument()
    expect(within(screen.getByLabelText("Outcomes")).getByText("12")).toBeInTheDocument()
    expect(repo.getTrackRecord).toHaveBeenLastCalledWith(20)

    await userEvent.click(screen.getByRole("button", { name: "1 week" }))
    expect(repo.getTrackRecord).toHaveBeenLastCalledWith(5)
    expect(screen.getByRole("button", { name: "1 week" })).toHaveAttribute("aria-pressed", "true")
  })
})

describe("TrackRecordCard", () => {
  it("shows a skeleton while loading", () => {
    renderWithProviders(<TrackRecordCard symbol="AAPL" />, { symbols: symbols(() => pending()) })
    expect(screen.getByLabelText("Loading track record")).toBeInTheDocument()
  })

  it("shows the error", async () => {
    const getOutcomes = jest.fn(async () => {
      throw new Error("nope")
    })
    renderWithProviders(<TrackRecordCard symbol="AAPL" />, { symbols: symbols(getOutcomes) })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the track record: nope")
  })

  it("explains that nothing has settled yet", async () => {
    const getOutcomes = jest.fn(async () => ({ ...symbolTrackRecord, calls: [] }))
    renderWithProviders(<TrackRecordCard symbol="AAPL" />, { symbols: symbols(getOutcomes) })
    expect(await screen.findByText(/No settled recommendations yet \(2 pending\)/)).toBeInTheDocument()
  })

  it("lists past calls with their alpha and result", async () => {
    const getOutcomes = jest.fn(async () => symbolTrackRecord)
    renderWithProviders(<TrackRecordCard symbol="AAPL" />, { symbols: symbols(getOutcomes) })

    const table = await screen.findByRole("table", { name: "Past recommendations" })
    const [, newest, oldest] = within(table).getAllByRole("row") as [HTMLElement, HTMLElement, HTMLElement]
    expect(within(newest).getByText("Sep 22, 2026")).toBeInTheDocument()
    expect(within(newest).getByText("Wrong")).toHaveClass("text-bad")
    expect(within(newest).getByText("SPY +1.20%")).toBeInTheDocument()
    expect(within(oldest).getByText("Right")).toHaveClass("text-ok")
    expect(within(oldest).getByText("+2.80%")).toHaveClass("text-ok")
    expect(screen.getByText(/of 2 calls \(50%\)/)).toBeInTheDocument()
    expect(getOutcomes).toHaveBeenLastCalledWith("AAPL", 20)

    await userEvent.click(screen.getByRole("button", { name: "3 months" }))
    expect(getOutcomes).toHaveBeenLastCalledWith("AAPL", 60)
  })
})
