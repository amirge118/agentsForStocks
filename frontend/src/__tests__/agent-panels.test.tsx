import { screen, within } from "@testing-library/react"

import { AgentPanels } from "@/components/features/stocks/agent-panels"
import { ScoreHistoryChart } from "@/components/features/stocks/score-history-chart"
import type { AgentRepository, SymbolRepository } from "@/lib/api/repositories"
import { agentResults } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"

function symbols(getResults: SymbolRepository["getResults"]): SymbolRepository {
  return { getAll: jest.fn(), getRecommendation: jest.fn(), getResults, getPrices: jest.fn() }
}

const agents: AgentRepository = {
  getAll: async () =>
    ["technicals", "valuation", "moat", "risk", "earnings", "recommendation"].map((name) => ({
      name,
      description: `${name} agent`,
      depends_on: [],
      recommendation_weight: 10,
      profile: { provider: "anthropic", model: null, skills: [], use_llm: true },
    })),
}

describe("AgentPanels", () => {
  it("shows a skeleton, then an error, then an empty state", async () => {
    const { unmount } = renderWithProviders(<AgentPanels symbol="AAPL" />, { symbols: symbols(() => pending()), agents })
    expect(screen.getByLabelText("Loading agent results")).toBeInTheDocument()
    unmount()

    const failing = renderWithProviders(<AgentPanels symbol="AAPL" />, {
      symbols: symbols(() => Promise.reject(new Error("down"))),
      agents,
    })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the agent results: down")
    failing.unmount()

    renderWithProviders(<AgentPanels symbol="AAPL" />, { symbols: symbols(async () => []), agents })
    expect(await screen.findByText("No agent has analysed AAPL yet.")).toBeInTheDocument()
  })

  it("renders one panel per analyst, newest result, in pipeline order", async () => {
    renderWithProviders(<AgentPanels symbol="AAPL" />, { symbols: symbols(async () => agentResults), agents })
    const panels = await screen.findAllByRole("article")
    expect(panels.map((p) => p.getAttribute("aria-label"))).toEqual([
      "technicals analysis",
      "valuation analysis",
      "moat analysis",
      "risk analysis",
      "earnings analysis",
    ])

    const moat = screen.getByRole("article", { name: "moat analysis" })
    expect(within(moat).getByText("80%")).toBeInTheDocument() // newest run, not the older 10%
    expect(within(moat).getByText("No data from: edgar")).toBeInTheDocument()

    const valuation = screen.getByRole("article", { name: "valuation analysis" })
    expect(within(valuation).getByText("+12.00%")).toHaveClass("text-ok")
    expect(within(valuation).getByText("$3,260B")).toBeInTheDocument()

    const technicals = screen.getByRole("article", { name: "technicals analysis" })
    expect(within(technicals).getByText("mean rev")).toBeInTheDocument()
    expect(within(technicals).getByText("-0.20")).toHaveClass("text-bad")

    const risk = screen.getByRole("article", { name: "risk analysis" })
    expect(within(risk).getByText("0.90")).toHaveClass("text-bad") // current ratio below 1

    // A payload that doesn't match falls back instead of breaking the page
    const earnings = screen.getByRole("article", { name: "earnings analysis" })
    expect(within(earnings).getByText(/unexpected shape/)).toBeInTheDocument()
  })
})

describe("AgentPanels variants", () => {
  it("lists fundamentals factors and splits sentiment into insider and news", async () => {
    const row = (agent_type: string, result: Record<string, unknown>) => ({
      ...agentResults[1]!,
      agent_type,
      run_id: agent_type,
      result: { signal: "bullish", confidence: 60, reasoning: "r", ...result },
    })
    const rows = [
      row("fundamentals", {
        factors: [
          { name: "profit_margin", signal: "bullish", score: 1, detail: "28%" },
          { name: "debt", signal: "bearish", score: -1, detail: "high" },
          { name: "growth", signal: "neutral", score: 0, detail: "flat" },
        ],
      }),
      row("sentiment", {
        insider: { signal: "bearish", confidence: 55, detail: "3 sales" },
        news: { signal: "bullish", confidence: 70, detail: "upbeat" },
      }),
      row("earnings", { quarters_analyzed: 8, beat_rate: 0.75, avg_surprise_pct: 4.2, next_earnings: "2026-10-29" }),
    ]
    renderWithProviders(<AgentPanels symbol="AAPL" />, { symbols: symbols(async () => rows), agents })

    const fundamentals = await screen.findByRole("article", { name: "fundamentals analysis" })
    expect(within(fundamentals).getByLabelText("bullish")).toHaveTextContent("✓")
    expect(within(fundamentals).getByLabelText("bearish")).toHaveTextContent("✗")
    expect(within(fundamentals).getByText("profit margin")).toBeInTheDocument()

    const sentiment = screen.getByRole("article", { name: "sentiment analysis" })
    expect(within(sentiment).getByText("bearish 55%")).toHaveClass("text-bad")
    expect(within(sentiment).getByText("bullish 70%")).toHaveClass("text-ok")

    const earnings = screen.getByRole("article", { name: "earnings analysis" })
    expect(within(earnings).getByText("75%")).toHaveClass("text-ok")
    expect(within(earnings).getByText("+4.20%")).toBeInTheDocument()
    expect(within(earnings).getByText("2026-10-29")).toBeInTheDocument()
  })
})

describe("ScoreHistoryChart", () => {
  it("waits for a second run before drawing a history", async () => {
    renderWithProviders(<ScoreHistoryChart symbol="AAPL" />, {
      symbols: symbols(async () => agentResults.filter((r) => r.agent_type === "recommendation").slice(0, 1)),
    })
    expect(await screen.findByText(/after the second daily run/)).toBeInTheDocument()
  })

  it("summarises the history for screen readers", async () => {
    renderWithProviders(<ScoreHistoryChart symbol="AAPL" />, {
      symbols: symbols(async () => agentResults.filter((r) => r.agent_type === "recommendation")),
    })
    expect(await screen.findByRole("img", { name: /Score from -20.0 on Oct 21, 2026 to \+42.5 on Oct 23, 2026/ })).toBeInTheDocument()
    expect(screen.getByText("3 runs, Oct 21, 2026 to Oct 23, 2026")).toBeInTheDocument()
  })

  it("reports a failed load", async () => {
    renderWithProviders(<ScoreHistoryChart symbol="AAPL" />, { symbols: symbols(() => Promise.reject(new Error("boom"))) })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the score history: boom")
  })
})
