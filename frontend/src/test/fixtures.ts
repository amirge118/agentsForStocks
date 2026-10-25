import type { AgentRun, Recommendation, SymbolOverview } from "@/types/api"

export const recommendation: Recommendation = {
  symbol: "AAPL",
  run_date: "2026-10-23",
  updated_at: "2026-10-23T22:30:00Z",
  action: "BUY",
  signal: "bullish",
  confidence: 72,
  weighted_score: 42.5,
  reasoning: "Wide moat and accelerating services growth",
  summary: "RECOMMENDATION: BUY",
  agents_available: 7,
  agents_missing: ["institutional"],
  risk_override_applied: false,
  agent_breakdown: [
    { agent: "moat", signal: "bullish", confidence: 80, weight: 15, contribution: 12, reasoning: "brand" },
    { agent: "risk", signal: "bearish", confidence: 40, weight: 15, contribution: -6, reasoning: "litigation" },
    { agent: "institutional", signal: "missing", confidence: 0, weight: 5, contribution: 0, reasoning: "" },
  ],
}

export const overview: SymbolOverview[] = [
  { symbol: "AAPL", recommendation },
  { symbol: "MSFT", recommendation: null },
]

export const runs: AgentRun[] = [
  {
    run_id: "r1", pipeline_run_id: "p1", agent_type: "financial_history", symbol: "AAPL",
    run_date: "2026-10-23", status: "completed", error: null,
    started_at: "2026-10-23T22:30:00Z", finished_at: "2026-10-23T22:30:05Z",
  },
  {
    run_id: "r2", pipeline_run_id: "p1", agent_type: "moat", symbol: "AAPL",
    run_date: "2026-10-23", status: "failed", error: "provider down",
    started_at: "2026-10-23T22:31:00Z", finished_at: "2026-10-23T22:31:02Z",
  },
]
