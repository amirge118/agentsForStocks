import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { AgentRunsTable } from "@/components/features/agents/agent-runs-table"
import { RecommendationCard } from "@/components/features/stocks/recommendation-card"
import { ApiError } from "@/lib/api/client"
import type { RunRepository, SymbolRepository } from "@/lib/api/repositories"
import { recommendation, runs } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"

function symbols(getRecommendation: SymbolRepository["getRecommendation"]): SymbolRepository {
  return { getAll: jest.fn(), getRecommendation, getResults: jest.fn(), getPrices: jest.fn() }
}

function runRepo(getAll: RunRepository["getAll"]): RunRepository {
  return { getAll, create: jest.fn() }
}

describe("RecommendationCard", () => {
  it("shows a skeleton while loading", () => {
    renderWithProviders(<RecommendationCard symbol="AAPL" />, { symbols: symbols(() => pending()) })
    expect(screen.getByLabelText("Loading recommendation")).toBeInTheDocument()
  })

  it("explains when there is no recommendation yet (404)", async () => {
    const notFound = () => Promise.reject(new ApiError("not found", 404))
    renderWithProviders(<RecommendationCard symbol="MSFT" />, { symbols: symbols(notFound) })
    expect(await screen.findByRole("status")).toHaveTextContent("No recommendation for MSFT yet")
  })

  it("shows other errors as alerts", async () => {
    const broken = () => Promise.reject(new ApiError("server error", 500))
    renderWithProviders(<RecommendationCard symbol="AAPL" />, { symbols: symbols(broken) })
    expect(await screen.findByRole("alert")).toHaveTextContent("server error")
  })

  it("renders the recommendation and the analyst breakdown", async () => {
    renderWithProviders(<RecommendationCard symbol="AAPL" />, {
      symbols: symbols(async () => recommendation),
    })
    expect(await screen.findByText("Wide moat and accelerating services growth")).toBeInTheDocument()
    expect(screen.getByText("Missing analysts: institutional")).toBeInTheDocument()
    expect(screen.getByText("+12.0")).toHaveClass("text-ok")
    expect(screen.getByText("-6.0")).toHaveClass("text-bad")
    expect(screen.getByText("—")).toBeInTheDocument() // missing analyst has no confidence
    expect(screen.queryByText(/Risk override/)).not.toBeInTheDocument()
  })

  it("marks analysts whose reasoning was flagged or replaced in the breakdown", async () => {
    const status = { moat: "fail", risk: "flag" } as const
    const marked = {
      ...recommendation,
      agent_breakdown: recommendation.agent_breakdown.map((c) => ({
        ...c,
        compliance_status: c.agent in status ? status[c.agent as keyof typeof status] : null,
        compliance_findings:
          c.agent === "moat"
            ? [{ rule: "promissory_language", severity: "fail" as const, phrase: "risk-free" }]
            : [],
      })),
    }
    renderWithProviders(<RecommendationCard symbol="AAPL" />, { symbols: symbols(async () => marked) })

    const table = await screen.findByRole("table", { name: "Agent breakdown" })
    const row = (agent: string) => within(table).getByRole("row", { name: new RegExp(`^${agent}`) })
    expect(within(row("moat")).getByLabelText("Compliance: original reasoning replaced")).toHaveTextContent(
      "Replaced",
    )
    expect(within(row("risk")).getByLabelText("Compliance: flagged")).toHaveTextContent("Flagged")
    expect(within(row("institutional")).queryByLabelText(/^Compliance:/)).not.toBeInTheDocument()

    await userEvent.tab() // the only focusable marker: moat has findings
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Promissory language “risk-free”")
  })

  it("shows no breakdown markers when every analyst passed or predates the review", async () => {
    renderWithProviders(<RecommendationCard symbol="AAPL" />, {
      symbols: symbols(async () => recommendation),
    })
    const table = await screen.findByRole("table", { name: "Agent breakdown" })
    expect(within(table).queryByLabelText(/^Compliance:/)).not.toBeInTheDocument()
  })

  it("always shows the disclaimer and hides the compliance badge when it passed", async () => {
    renderWithProviders(<RecommendationCard symbol="AAPL" />, {
      symbols: symbols(async () => recommendation),
    })
    expect(await screen.findByText(/not investment advice/)).toBeInTheDocument()
    expect(screen.queryByLabelText("Compliance review")).not.toBeInTheDocument()
  })

  it("shows compliance findings when the reasoning was replaced or flagged", async () => {
    const failed = {
      ...recommendation,
      compliance: {
        status: "fail" as const,
        findings: [
          { rule: "promissory_language", severity: "fail" as const, phrase: "guaranteed" },
          { rule: "missing_risk_discussion", severity: "flag" as const, phrase: "" },
          { rule: "custom_rule", severity: "flag" as const, phrase: "" },
        ],
        original_reasoning: "guaranteed gains",
      },
    }
    const { unmount } = renderWithProviders(<RecommendationCard symbol="AAPL" />, {
      symbols: symbols(async () => failed),
    })
    const notice = await screen.findByLabelText("Compliance review")
    expect(notice).toHaveTextContent("Compliance: original reasoning replaced")
    expect(notice).toHaveTextContent("Promissory language “guaranteed”")
    expect(notice).toHaveTextContent("No risk discussed")
    expect(notice).toHaveTextContent("custom_rule")
    unmount()

    const flagged = { ...failed, compliance: { ...failed.compliance, status: "flag" as const } }
    renderWithProviders(<RecommendationCard symbol="AAPL" />, { symbols: symbols(async () => flagged) })
    expect(await screen.findByText("Compliance: flagged")).toBeInTheDocument()
  })

  it("flags a risk override", async () => {
    const overridden = { ...recommendation, risk_override_applied: true, agents_missing: [] }
    renderWithProviders(<RecommendationCard symbol="AAPL" />, {
      symbols: symbols(async () => overridden),
    })
    expect(await screen.findByText(/Risk override applied/)).toBeInTheDocument()
  })
})

describe("AgentRunsTable", () => {
  it("covers loading, error, empty and success states", async () => {
    const { unmount } = renderWithProviders(<AgentRunsTable />, { runs: runRepo(() => pending()) })
    expect(screen.getByLabelText("Loading runs")).toBeInTheDocument()
    unmount()

    const failed = renderWithProviders(<AgentRunsTable />, {
      runs: runRepo(() => Promise.reject(new Error("timeout"))),
    })
    expect(await screen.findByRole("alert")).toHaveTextContent("timeout")
    failed.unmount()

    const empty = renderWithProviders(<AgentRunsTable />, { runs: runRepo(async () => []) })
    expect(await screen.findByText("No agent runs yet.")).toBeInTheDocument()
    empty.unmount()

    const getAll = jest.fn(async () => runs)
    renderWithProviders(<AgentRunsTable filters={{ symbol: "AAPL" }} />, { runs: runRepo(getAll) })
    expect(await screen.findByText("financial history")).toBeInTheDocument()
    expect(screen.getByText("failed")).toHaveClass("text-bad")
    expect(screen.getByText("provider down")).toBeInTheDocument()
    expect(getAll).toHaveBeenCalledWith({ symbol: "AAPL" })
  })
})

describe("AgentErrorBoundary", () => {
  it("contains a crashing agent widget", () => {
    const Boom = () => {
      throw new Error("render failed")
    }
    jest.spyOn(console, "error").mockImplementation(() => undefined) // React logs caught errors
    render(
      <AgentErrorBoundary label="The moat panel">
        <Boom />
      </AgentErrorBoundary>,
    )
    expect(screen.getByRole("alert")).toHaveTextContent("The moat panel could not be displayed.")
  })
})
