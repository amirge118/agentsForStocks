import type { AgentRun, LLMCall, LLMUsageReport, Recommendation, SymbolOverview } from "@/types/api"

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
  compliance: { status: "pass", findings: [], original_reasoning: null },
  disclaimer: "This is an automated analysis for informational purposes only and is not investment advice.",
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

export const completedRun: AgentRun = {
    run_id: "r1", pipeline_run_id: "p1", agent_type: "financial_history", symbol: "AAPL",
    run_date: "2026-10-23", status: "completed", error: null,
    started_at: "2026-10-23T22:30:00Z", finished_at: "2026-10-23T22:30:05Z",
    fetch_ms: 1200, analyze_ms: 3400, llm_calls: 1, input_tokens: 1850, output_tokens: 96,
    cost_usd: 0.00233, llm_fallbacks: 0,
}
export const failedRun: AgentRun = {
    run_id: "r2", pipeline_run_id: "p1", agent_type: "moat", symbol: "AAPL",
    run_date: "2026-10-23", status: "failed", error: "provider down",
    started_at: "2026-10-23T22:31:00Z", finished_at: "2026-10-23T22:31:02Z",
    fetch_ms: null, analyze_ms: null, llm_calls: 0, input_tokens: 0, output_tokens: 0,
    cost_usd: null, llm_fallbacks: 0,
}
export const runs: AgentRun[] = [completedRun, failedRun]

export const llmUsage: LLMUsageReport = {
  since: "2026-10-16T22:30:00Z",
  group_by: "agent",
  rows: [
    {
      key: "risk", calls: 9, errors: 1, input_tokens: 19800, output_tokens: 860,
      cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0.0241, avg_latency_ms: 1840,
    },
    {
      key: "technicals", calls: 9, errors: 0, input_tokens: 1210, output_tokens: 700,
      cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0.0047, avg_latency_ms: 910,
    },
  ],
  total_calls: 18,
  total_input_tokens: 21010,
  total_output_tokens: 1560,
  total_cost_usd: 0.0288,
}

export const llmCall: LLMCall = {
    call_id: "c1", created_at: "2026-10-23T22:30:03Z", pipeline_run_id: "p1", run_id: "r1",
    agent: "financial_history", symbol: "AAPL", model: "claude-haiku-4-5",
    prompt_name: "financial_history", prompt_version: "3f9a1c2b7d10", status: "ok",
    stop_reason: "end_turn", error: null, latency_ms: 1420, input_tokens: 1850,
    output_tokens: 96, cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0.00233,
    system_prompt: "You are a financial analyst reviewing five years of financial statements.",
    prompt: "Symbol: AAPL\nRevenue CAGR: +8.1%",
    response: '{"signal":"bullish","confidence":72,"reasoning":"Steady growth"}',
}
export const llmCalls: LLMCall[] = [llmCall]
