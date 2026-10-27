import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { PriceChart } from "@/components/features/stocks/price-chart"
import { ApiError } from "@/lib/api/client"
import type { SymbolRepository } from "@/lib/api/repositories"
import { agentResults, priceHistory } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"

const replace = jest.fn()
let search = ""
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/symbols/AAPL",
  useSearchParams: () => new URLSearchParams(search),
}))

// The canvas library needs a real browser; E2E covers the drawing itself
jest.mock("lightweight-charts", () => {
  const series = { setData: jest.fn(), createPriceLine: jest.fn() }
  return {
    createChart: () => ({
      addSeries: () => series,
      panes: () => [{ setStretchFactor: jest.fn() }, { setStretchFactor: jest.fn() }, { setStretchFactor: jest.fn() }],
      timeScale: () => ({ fitContent: jest.fn() }),
      remove: jest.fn(),
    }),
    createSeriesMarkers: jest.fn(),
    LineSeries: {},
    HistogramSeries: {},
    CrosshairMode: { Magnet: 1 },
    LineStyle: { Dashed: 2 },
  }
  // virtual: the package's exports only name the development / production conditions Jest doesn't use
}, { virtual: true })

function symbols(getPrices: SymbolRepository["getPrices"]): SymbolRepository {
  return {
    getAll: jest.fn(),
    getRecommendation: jest.fn(),
    getResults: async () => agentResults.filter((r) => r.agent_type === "recommendation"),
    getPrices,
    getOutcomes: jest.fn(),
  }
}

describe("PriceChart", () => {
  beforeEach(() => {
    replace.mockClear()
    search = ""
  })

  it("loads the range from the URL (6M by default) and shows the last close and change", async () => {
    const getPrices = jest.fn(async () => priceHistory)
    renderWithProviders(<PriceChart symbol="AAPL" />, { symbols: symbols(getPrices) })
    expect(screen.getByLabelText("Loading prices")).toBeInTheDocument()
    expect(await screen.findByText("$235.00")).toBeInTheDocument()
    expect(screen.getByText("+2.17%")).toHaveClass("text-ok")
    expect(screen.getByRole("img", { name: "AAPL price, 6M" })).toBeInTheDocument()
    expect(getPrices).toHaveBeenCalledWith("AAPL", "6M")
    expect(screen.getByRole("button", { name: "6M" })).toHaveAttribute("aria-pressed", "true")
  })

  it("keeps the chosen range in the URL", async () => {
    search = "range=1M&tab=x"
    const getPrices = jest.fn(async () => priceHistory)
    renderWithProviders(<PriceChart symbol="AAPL" />, { symbols: symbols(getPrices) })
    expect(getPrices).toHaveBeenCalledWith("AAPL", "1M")
    await userEvent.click(screen.getByRole("button", { name: "1Y" }))
    expect(replace).toHaveBeenCalledWith("/symbols/AAPL?range=1Y&tab=x", { scroll: false })
  })

  it("says so when the price provider is down, and when there are no bars", async () => {
    const down = renderWithProviders(<PriceChart symbol="AAPL" />, {
      symbols: symbols(() => Promise.reject(new ApiError("bad gateway", 502))),
    })
    expect(await screen.findByText(/Price data is unavailable right now/)).toBeInTheDocument()
    down.unmount()

    const empty = renderWithProviders(<PriceChart symbol="AAPL" />, {
      symbols: symbols(async () => ({ ...priceHistory, bars: [] })),
    })
    expect(await screen.findByText("No price data for AAPL.")).toBeInTheDocument()
    empty.unmount()

    renderWithProviders(<PriceChart symbol="AAPL" />, { symbols: symbols(() => Promise.reject(new Error("boom"))) })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load prices: boom")
  })

  it("keeps a pending request in the loading state", () => {
    renderWithProviders(<PriceChart symbol="AAPL" />, { symbols: symbols(() => pending()) })
    expect(screen.getByLabelText("Loading prices")).toBeInTheDocument()
  })
})
