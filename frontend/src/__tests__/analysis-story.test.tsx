import { screen } from "@testing-library/react"

import { AnalysisStory } from "@/components/features/stocks/analysis-story"
import { ApiError } from "@/lib/api/client"
import type { AgentRepository, SymbolRepository } from "@/lib/api/repositories"
import { agentResults, recommendation } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"

function symbols(over: Partial<SymbolRepository>): SymbolRepository {
  return {
    getAll: jest.fn(),
    getRecommendation: async () => recommendation,
    getResults: async () => agentResults,
    getPrices: jest.fn(),
    getOutcomes: jest.fn(),
    ...over,
  }
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

describe("AnalysisStory", () => {
  it("shows a skeleton while loading", () => {
    renderWithProviders(<AnalysisStory symbol="AAPL" />, { symbols: symbols({ getRecommendation: () => pending() }), agents })
    expect(screen.getByLabelText("Loading the analysis")).toBeInTheDocument()
  })

  it("has no story to tell without a recommendation", async () => {
    const notFound = () => Promise.reject(new ApiError("not found", 404))
    renderWithProviders(<AnalysisStory symbol="MSFT" />, { symbols: symbols({ getRecommendation: notFound }), agents })
    expect(await screen.findByText(/No recommendation for MSFT yet/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Back to MSFT" })).toHaveAttribute("href", "/symbols/MSFT")
  })

  it("shows other errors as alerts", async () => {
    const broken = () => Promise.reject(new Error("results down"))
    renderWithProviders(<AnalysisStory symbol="AAPL" />, { symbols: symbols({ getResults: broken }), agents })
    expect(await screen.findByRole("alert")).toHaveTextContent("results down")
  })

  it("tells one act per analyst in pipeline order, then the disagreement, then the verdict", async () => {
    renderWithProviders(<AnalysisStory symbol="AAPL" />, { symbols: symbols({}), agents })

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("BUY, SELL or HOLD for AAPL?")
    const acts = screen.getAllByRole("region", { name: /analyst \d of 5/ })
    expect(acts.map((a) => a.getAttribute("aria-label"))).toEqual([
      "technicals, analyst 1 of 5",
      "valuation, analyst 2 of 5",
      "moat, analyst 3 of 5",
      "risk, analyst 4 of 5",
      "earnings, analyst 5 of 5",
    ])
    expect(screen.getByText("It worked without: edgar.")).toBeInTheDocument()
    expect(screen.getByText(/unexpected shape/)).toBeInTheDocument() // malformed earnings row
    expect(screen.getByRole("heading", { name: "They don’t all agree." })).toBeInTheDocument()

    const verdict = screen.getByRole("region", { name: "The verdict" })
    expect(verdict).toHaveTextContent("BUY")
    expect(verdict).toHaveTextContent("+42.5")
    expect(verdict).toHaveTextContent(recommendation.reasoning)
    expect(screen.getByText(recommendation.disclaimer)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "See every figure for AAPL" })).toHaveAttribute("href", "/symbols/AAPL")
  })
})
