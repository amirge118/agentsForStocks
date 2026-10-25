import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { AgentRunsTable } from "@/components/features/agents/agent-runs-table"
import { LLMCallsList } from "@/components/features/llm/llm-calls-list"
import { UsageTable } from "@/components/features/llm/usage-table"
import type { LLMRepository, RunRepository } from "@/lib/api/repositories"
import { formatCost, formatTokens } from "@/lib/format"
import { completedRun, failedRun, llmCall, llmCalls, llmUsage } from "@/test/fixtures"
import { pending, renderWithProviders } from "@/test/render"

function llm(overrides: Partial<LLMRepository> = {}): LLMRepository {
  return {
    getUsage: jest.fn(async () => llmUsage),
    getRunCalls: jest.fn(async () => llmCalls),
    ...overrides,
  }
}

describe("UsageTable", () => {
  it("shows a skeleton while loading", () => {
    renderWithProviders(<UsageTable />, { llm: llm({ getUsage: () => pending() }) })
    expect(screen.getByLabelText("Loading usage")).toBeInTheDocument()
  })

  it("shows the error", async () => {
    const getUsage = jest.fn(async () => {
      throw new Error("backend down")
    })
    renderWithProviders(<UsageTable />, { llm: llm({ getUsage }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("backend down")
  })

  it("shows an empty state", async () => {
    const getUsage = jest.fn(async () => ({ ...llmUsage, rows: [] }))
    renderWithProviders(<UsageTable />, { llm: llm({ getUsage }) })
    expect(await screen.findByText("No LLM calls in this period.")).toBeInTheDocument()
  })

  it("renders totals and rows, and refetches when the grouping or period changes", async () => {
    const repo = llm()
    renderWithProviders(<UsageTable />, { llm: repo })

    const table = await screen.findByRole("table", { name: "LLM usage" })
    expect(within(table).getByText("risk")).toBeInTheDocument()
    expect(within(table).getByText("19,800")).toBeInTheDocument()
    expect(within(table).getByText("$0.0241")).toBeInTheDocument()
    expect(within(screen.getByLabelText("Totals")).getByText("$0.0288")).toBeInTheDocument()
    expect(repo.getUsage).toHaveBeenLastCalledWith(7, "agent")

    await userEvent.click(screen.getByRole("button", { name: "Model" }))
    await userEvent.click(screen.getByRole("button", { name: "30d" }))
    expect(repo.getUsage).toHaveBeenLastCalledWith(30, "model")
    expect(screen.getByRole("button", { name: "30d" })).toHaveAttribute("aria-pressed", "true")
  })
})

describe("LLMCallsList", () => {
  it("shows the prompts sent and the reply", async () => {
    const repo = llm()
    renderWithProviders(<LLMCallsList runId="r1" />, { llm: repo })

    const list = await screen.findByRole("list", { name: "LLM calls" })
    expect(within(list).getByText("claude-haiku-4-5")).toBeInTheDocument()
    expect(within(list).getByText("financial_history@3f9a1c2b7d10")).toBeInTheDocument()
    expect(within(list).getByText(/five years of financial statements/)).toBeInTheDocument()
    expect(within(list).getByText(/"signal":"bullish"/)).toBeInTheDocument()
    expect(repo.getRunCalls).toHaveBeenCalledWith("r1")
  })

  it("says when content was not captured, and when there were no calls", async () => {
    const hidden = { ...llmCall, system_prompt: null, prompt: null, response: null }
    renderWithProviders(<LLMCallsList runId="r1" />, {
      llm: llm({ getRunCalls: jest.fn(async () => [hidden]) }),
    })
    expect(await screen.findAllByText(/Not captured/)).toHaveLength(3)

    renderWithProviders(<LLMCallsList runId="r2" />, {
      llm: llm({ getRunCalls: jest.fn(async () => []) }),
    })
    expect(await screen.findByText("This run made no LLM calls.")).toBeInTheDocument()
  })
})

describe("AgentRunsTable LLM columns", () => {
  it("links runs that called the model to their prompts and marks fallbacks", async () => {
    const withFallback = { ...failedRun, run_id: "r3", status: "completed" as const, llm_fallbacks: 1 }
    const repo: RunRepository = { getAll: jest.fn(async () => [completedRun, withFallback]), create: jest.fn() }
    renderWithProviders(<AgentRunsTable />, { runs: repo })

    const link = await screen.findByRole("link", { name: "1,850 / 96" })
    expect(link).toHaveAttribute("href", "/runs/r1")
    expect(screen.getByText("$0.0023")).toBeInTheDocument()
    expect(screen.getByText("fallback")).toBeInTheDocument()
  })
})

describe("LLM formatting", () => {
  it("formats costs and token counts", () => {
    expect(formatCost(0.00233)).toBe("$0.0023")
    expect(formatCost(1.5)).toBe("$1.50")
    expect(formatCost(null)).toBe("—")
    expect(formatTokens(123456)).toBe("123,456")
  })
})
