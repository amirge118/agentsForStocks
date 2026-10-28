import type {
  AgentResult,
  AgentRun,
  LLMCall,
  LLMProvider,
  LLMUsageReport,
  PriceHistory,
  Recommendation,
  SymbolOverview,
  SymbolTrackRecord,
  TrackRecordReport,
} from "@/types/api"

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
  needs_review: [],
  risk_override_applied: false,
  compliance: { status: "pass", findings: [], original_reasoning: null },
  disclaimer: "This is an automated analysis for informational purposes only and is not investment advice.",
  agent_breakdown: [
    { agent: "moat", signal: "bullish", confidence: 80, weight: 15, contribution: 12, reasoning: "brand", needs_review: false },
    { agent: "risk", signal: "bearish", confidence: 40, weight: 15, contribution: -6, reasoning: "litigation", needs_review: false },
    { agent: "institutional", signal: "missing", confidence: 0, weight: 5, contribution: 0, reasoning: "", needs_review: false },
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
    agent: "financial_history", symbol: "AAPL", provider: "anthropic", model: "claude-haiku-4-5",
    prompt_name: "financial_history", prompt_version: "3f9a1c2b7d10", status: "ok",
    stop_reason: "end_turn", error: null, latency_ms: 1420, input_tokens: 1850,
    output_tokens: 96, cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0.00233,
    system_prompt: "You are a financial analyst reviewing five years of financial statements.",
    prompt: "Symbol: AAPL\nRevenue CAGR: +8.1%",
    response: '{"signal":"bullish","confidence":72,"reasoning":"Steady growth"}',
}
export const llmCalls: LLMCall[] = [llmCall]

export const gemini: LLMProvider = {
  name: "gemini", model: "gemini-3.5-flash-lite", structured_mode: "json_schema",
  chain_position: 1, rpm: 10, tpm: 250000, rpd: 1000, tpd: null,
  day_start: "2026-10-23T07:00:00Z", day_requests: 950, day_tokens: 410000,
}
export const claude: LLMProvider = {
  name: "anthropic", model: "claude-haiku-4-5", structured_mode: "native",
  chain_position: null, rpm: null, tpm: null, rpd: null, tpd: null,
  day_start: "2026-10-23T00:00:00Z", day_requests: 12, day_tokens: 30000,
}
export const llmProviders: LLMProvider[] = [claude, gemini]

export const trackRecord: TrackRecordReport = {
  horizon: 20, since: null, settled: 12, pending: 4, unavailable: 1,
  agents: [
    {
      agent: "recommendation",
      overall: { calls: 3, hits: 2, hit_rate: 2 / 3, mean_alpha_captured: 0.0123 },
      by_signal: [
        { key: "bullish", calls: 2, hits: 2, hit_rate: 1, mean_alpha_captured: 0.025 },
        { key: "bearish", calls: 1, hits: 0, hit_rate: 0, mean_alpha_captured: -0.0131 },
      ],
      by_confidence: [
        { key: "60-80", calls: 2, hits: 1, hit_rate: 0.5, mean_alpha_captured: 0.004 },
        { key: "80-100", calls: 1, hits: 1, hit_rate: 1, mean_alpha_captured: 0.03 },
      ],
    },
    {
      agent: "financial_history",
      overall: { calls: 3, hits: 1, hit_rate: 1 / 3, mean_alpha_captured: -0.004 },
      by_signal: [{ key: "neutral", calls: 3, hits: 1, hit_rate: 1 / 3, mean_alpha_captured: 0 }],
      by_confidence: [{ key: "40-60", calls: 3, hits: 1, hit_rate: 1 / 3, mean_alpha_captured: 0 }],
    },
  ],
}

export const symbolTrackRecord: SymbolTrackRecord = {
  symbol: "AAPL", horizon: 20, pending: 2,
  overall: { calls: 2, hits: 1, hit_rate: 0.5, mean_alpha_captured: 0.0045 },
  calls: [
    {
      decision_date: "2026-09-22", exit_date: "2026-10-20", signal: "bearish", confidence: 58,
      raw_return: 0.031, benchmark_return: 0.012, alpha: 0.019, hit: false, benchmark: "SPY",
    },
    {
      decision_date: "2026-09-01", exit_date: "2026-09-29", signal: "bullish", confidence: 72,
      raw_return: 0.041, benchmark_return: 0.013, alpha: 0.028, hit: true, benchmark: "SPY",
    },
  ],
}
export const priceHistory: PriceHistory = {
  symbol: "AAPL",
  range: "6M",
  bars: [
    { date: "2026-10-21", open: 228, high: 231, low: 227, close: 230, volume: 5e7, sma20: 226, sma50: 220, rsi14: 58 },
    { date: "2026-10-22", open: 230, high: 233, low: 229, close: 232.5, volume: 4.8e7, sma20: 226.5, sma50: 220.4, rsi14: 61 },
    { date: "2026-10-23", open: 232, high: 236, low: 231, close: 235, volume: 6.1e7, sma20: 227.1, sma50: 220.9, rsi14: 66 },
  ],
}

const resultRow = (agent_type: string, result: Record<string, unknown>, run_date = "2026-10-23"): AgentResult => ({
  agent_type,
  symbol: "AAPL",
  run_date,
  run_id: `${agent_type}-${run_date}`,
  updated_at: `${run_date}T22:30:00Z`,
  result,
})

const base = (signal: string, confidence: number, reasoning: string) => ({
  signal,
  confidence,
  reasoning,
  summary: `${signal} ${confidence}`,
  data_gaps: [],
  contract_violations: [],
})

/** Newest first, as /symbols/{symbol}/results returns them */
export const agentResults: AgentResult[] = [
  resultRow("recommendation", { ...recommendation, weighted_score: 42.5, action: "BUY" }),
  resultRow("valuation", {
    ...base("bullish", 70, "Trades below the DCF base case"),
    dcf: { bear: 2.6e12, base: 3.9e12, bull: 5.1e12 },
    earnings_power_value: 1.4e12,
    ev_ebitda_value: null,
    avg_intrinsic_value: 3.65e12,
    margin_of_safety: 0.12,
    market_cap: 3.26e12,
    growth_rate: 0.158,
    discount_rate: 0.097,
    implied_growth: 0.135,
  }),
  resultRow("technicals", {
    ...base("bullish", 64, "Trend and momentum agree"),
    strategies: { trend: 0.6, mean_rev: -0.2, momentum: 0.5, volatility: 0.1, stat_arb: 0 },
    composite: 0.31,
  }),
  resultRow("risk", {
    ...base("bearish", 40, "Litigation"),
    debt_to_equity: 1.8,
    current_ratio: 0.9,
    beta: 1.2,
    risk_keywords: ["litigation"],
  }),
  resultRow("moat", {
    ...base("bullish", 80, "Brand"),
    data_gaps: ["edgar"],
    needs_review: ["model unavailable for 1 judgement: a rule-based fallback was used"],
    contract_violations: ["bullish without a moat"],
  }),
  resultRow("earnings", { signal: "neutral" }), // malformed: no confidence / reasoning
  resultRow("moat", base("neutral", 10, "older run"), "2026-10-22"),
  resultRow("recommendation", { ...recommendation, weighted_score: 3, action: "HOLD" }, "2026-10-22"),
  resultRow("recommendation", { ...recommendation, weighted_score: -20, action: "SELL" }, "2026-10-21"),
]
