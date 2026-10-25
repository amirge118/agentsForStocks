import { screen, within } from "@testing-library/react"

import { AgentsTable } from "@/components/features/agents/agents-table"
import type { AgentRepository } from "@/lib/api/repositories"
import type { AgentInfo } from "@/types/api"
import { pending, renderWithProviders } from "@/test/render"

const agents: AgentInfo[] = [
  {
    name: "moat", description: "Competitive advantage", depends_on: [], recommendation_weight: 15,
    profile: { provider: "anthropic", model: null, skills: ["moat_evidence"], use_llm: true },
  },
  {
    name: "technicals", description: "Price trends", depends_on: [], recommendation_weight: 0,
    profile: { provider: "anthropic", model: null, skills: [], use_llm: false },
  },
  {
    name: "sentiment", description: "News", depends_on: [], recommendation_weight: 0,
    profile: { provider: "alt", model: "flash-lite", skills: [], use_llm: true },
  },
]

function repo(getAll: AgentRepository["getAll"]): AgentRepository {
  return { getAll }
}

describe("AgentsTable", () => {
  it("shows a skeleton, then the error", async () => {
    const { unmount } = renderWithProviders(<AgentsTable />, { agents: repo(() => pending()) })
    expect(screen.getByLabelText("Loading agents")).toBeInTheDocument()
    unmount()
    renderWithProviders(<AgentsTable />, { agents: repo(() => Promise.reject(new Error("down"))) })
    expect(await screen.findByRole("alert")).toHaveTextContent("down")
  })

  it("lists each agent's weight, model and skills", async () => {
    renderWithProviders(<AgentsTable />, { agents: repo(async () => agents) })
    const table = await screen.findByRole("table", { name: "Agents" })
    const rows = within(table).getAllByRole("row")
    expect(rows[1]).toHaveTextContent("moat")
    expect(rows[1]).toHaveTextContent("15")
    expect(rows[1]).toHaveTextContent("moat evidence")
    expect(rows[2]).toHaveTextContent("rule-based")
    expect(rows[2]).toHaveTextContent("info")
    expect(rows[3]).toHaveTextContent("alt · flash-lite")
  })
})
