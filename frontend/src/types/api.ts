/**
 * Runtime-validated API types.
 *
 * Every response is parsed with these Zod schemas at the API boundary. The
 * `Exact` assertions at the bottom fail the type-check if a schema drifts from
 * the backend contract generated into openapi.d.ts (`npm run generate:api`).
 */
import { z } from "zod"

import type { components } from "./openapi"

type Schemas = components["schemas"]

export const SignalSchema = z.enum(["bullish", "bearish", "neutral"])
export const ActionSchema = z.enum(["BUY", "SELL", "HOLD"])
export const RunStatusSchema = z.enum(["completed", "skipped", "reused", "failed"])
export const ComplianceStatusSchema = z.enum(["pass", "flag", "fail"])

export const ComplianceFindingSchema = z.object({
  rule: z.string(),
  severity: z.enum(["flag", "fail"]),
  phrase: z.string(),
})

export const ContributionSchema = z.object({
  agent: z.string(),
  signal: z.string(),
  confidence: z.number(),
  weight: z.number(),
  contribution: z.number(),
  reasoning: z.string(),
  compliance_status: ComplianceStatusSchema.nullish(),
  compliance_findings: z.array(ComplianceFindingSchema).optional(),
  needs_review: z.boolean(),
})

export const ComplianceSchema = z.object({
  status: ComplianceStatusSchema,
  findings: z.array(ComplianceFindingSchema),
  original_reasoning: z.string().nullish(),
})

export const RecommendationSchema = z.object({
  symbol: z.string().min(1).max(10),
  run_date: z.string(),
  updated_at: z.string(),
  action: ActionSchema,
  signal: SignalSchema,
  confidence: z.number().min(0).max(100),
  weighted_score: z.number(),
  reasoning: z.string(),
  summary: z.string(),
  agents_available: z.number().int(),
  agents_missing: z.array(z.string()),
  risk_override_applied: z.boolean(),
  compliance: ComplianceSchema,
  disclaimer: z.string(),
  agent_breakdown: z.array(ContributionSchema),
  needs_review: z.array(z.string()).optional(),
})

export const SymbolOverviewSchema = z.object({
  symbol: z.string(),
  recommendation: RecommendationSchema.nullable(),
})

export const AgentProfileSchema = z.object({
  provider: z.string(),
  model: z.string().nullable(),
  skills: z.array(z.string()),
  use_llm: z.boolean(),
})
export const AgentInfoSchema = z.object({
  name: z.string(),
  description: z.string(),
  depends_on: z.array(z.string()),
  recommendation_weight: z.number(),
  profile: AgentProfileSchema,
  refresh: z.object({ max_age_days: z.number(), on_new_report: z.boolean() }),
})

export const AgentResultSchema = z.object({
  agent_type: z.string(),
  symbol: z.string(),
  run_date: z.string(),
  run_id: z.string(),
  updated_at: z.string(),
  result: z.record(z.string(), z.unknown()),
})

export const AgentRunSchema = z.object({
  run_id: z.string(),
  pipeline_run_id: z.string().nullable(),
  agent_type: z.string(),
  symbol: z.string(),
  run_date: z.string(),
  status: RunStatusSchema,
  error: z.string().nullable(),
  started_at: z.string(),
  finished_at: z.string(),
  fetch_ms: z.number().nullable(),
  analyze_ms: z.number().nullable(),
  llm_calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cost_usd: z.number().nullable(),
  llm_fallbacks: z.number(),
  llm_reused: z.number(),
})
export const UsageGroupSchema = z.enum(["agent", "model", "provider", "day", "prompt_version"])
export const LLMCallSchema = z.object({
  call_id: z.string(),
  created_at: z.string(),
  pipeline_run_id: z.string().nullable(),
  run_id: z.string().nullable(),
  agent: z.string().nullable(),
  symbol: z.string().nullable(),
  provider: z.string().nullable(),
  model: z.string(),
  prompt_name: z.string().nullable(),
  prompt_version: z.string(),
  status: z.enum(["ok", "error"]),
  stop_reason: z.string().nullable(),
  error: z.string().nullable(),
  latency_ms: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cache_read_tokens: z.number(),
  cache_write_tokens: z.number(),
  cost_usd: z.number().nullable(),
  system_prompt: z.string().nullable(),
  prompt: z.string().nullable(),
  response: z.string().nullable(),
})
export const LLMUsageRowSchema = z.object({
  key: z.string(),
  calls: z.number(),
  errors: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cache_read_tokens: z.number(),
  cache_write_tokens: z.number(),
  cost_usd: z.number(),
  avg_latency_ms: z.number(),
})
export const LLMUsageReportSchema = z.object({
  since: z.string(),
  group_by: UsageGroupSchema,
  rows: z.array(LLMUsageRowSchema),
  total_calls: z.number(),
  total_input_tokens: z.number(),
  total_output_tokens: z.number(),
  total_cost_usd: z.number(),
})
export const LLMProviderSchema = z.object({
  name: z.string(),
  model: z.string(),
  structured_mode: z.string(),
  chain_position: z.number().nullable(),
  rpm: z.number().nullable(),
  tpm: z.number().nullable(),
  rpd: z.number().nullable(),
  tpd: z.number().nullable(),
  day_start: z.string(),
  day_requests: z.number(),
  day_tokens: z.number(),
})

export const TrackStatsSchema = z.object({
  calls: z.number(),
  hits: z.number(),
  hit_rate: z.number().nullable(),
  mean_alpha_captured: z.number().nullable(),
})
export const TrackGroupSchema = TrackStatsSchema.extend({ key: z.string() })
export const AgentTrackRecordSchema = z.object({
  agent: z.string(),
  overall: TrackStatsSchema,
  by_signal: z.array(TrackGroupSchema),
  by_confidence: z.array(TrackGroupSchema),
})
export const TrackRecordReportSchema = z.object({
  horizon: z.number(),
  since: z.string().nullable(),
  settled: z.number(),
  pending: z.number(),
  unavailable: z.number(),
  agents: z.array(AgentTrackRecordSchema),
})
export const OutcomeCallSchema = z.object({
  decision_date: z.string(),
  exit_date: z.string(),
  signal: SignalSchema,
  confidence: z.number(),
  raw_return: z.number(),
  benchmark_return: z.number(),
  alpha: z.number(),
  hit: z.boolean(),
  benchmark: z.string(),
})
export const SymbolTrackRecordSchema = z.object({
  symbol: z.string(),
  horizon: z.number(),
  overall: TrackStatsSchema,
  pending: z.number(),
  calls: z.array(OutcomeCallSchema),
})
/** Trading sessions after a call that the track record judges it on. */
export const HORIZONS = [5, 20, 60] as const
export type Horizon = (typeof HORIZONS)[number]

export const PipelineRunAcceptedSchema = z.object({
  pipeline_run_id: z.string(),
  run_date: z.string(),
  symbols: z.array(z.string()),
  agents: z.array(z.string()),
  force: z.boolean(),
})

export const PriceRangeSchema = z.enum(["1M", "3M", "6M", "1Y"])

export const PriceBarSchema = z.object({
  date: z.string(),
  open: z.number().nullable(),
  high: z.number().nullable(),
  low: z.number().nullable(),
  close: z.number(),
  volume: z.number().nullable(),
  sma20: z.number().nullable(),
  sma50: z.number().nullable(),
  rsi14: z.number().nullable(),
})

export const PriceHistorySchema = z.object({
  symbol: z.string(),
  range: PriceRangeSchema,
  bars: z.array(PriceBarSchema),
})

export const WatchlistItemSchema = z.object({
  symbol: z.string(),
  position: z.number().int(),
  added_at: z.string(),
})

// ---------------------------------------------------------------------------
// Portfolio ledger. The API replays the ledger in exact decimals and answers numbers.
// A position without any price has null price, value and P/L: never shown as 0.
// ---------------------------------------------------------------------------
export const TransactionKindSchema = z.enum(["DEPOSIT", "WITHDRAW", "BUY", "SELL", "DIVIDEND", "TRANSFER_IN"])

export const TransactionSchema = z.object({
  id: z.number().int(),
  trade_date: z.string(),
  kind: TransactionKindSchema,
  symbol: z.string().nullable(),
  shares: z.number().nullable(),
  price: z.number().nullable(),
  fee: z.number(),
  amount: z.number().nullable(),
  note: z.string().nullable(),
  created_at: z.string(),
})

export const PositionSchema = z.object({
  symbol: z.string(),
  shares: z.number(),
  avg_cost: z.number(),
  cost_basis: z.number(),
  realised_pnl: z.number(),
  dividends: z.number(),
  price: z.number().nullable(),
  price_as_of: z.string().nullable(),
  price_stale: z.boolean(),
  value: z.number().nullable(),
  unrealised_pnl: z.number().nullable(),
  unrealised_pct: z.number().nullable(),
  day_change: z.number().nullable(),
  weight: z.number().nullable(),
})

export const PortfolioSchema = z.object({
  cash: z.number(),
  holdings_value: z.number(),
  total_value: z.number(),
  unrealised_pnl: z.number(),
  day_change: z.number(),
  day_change_pct: z.number().nullable(),
  cost_basis: z.number(),
  deposited: z.number(),
  transferred_in: z.number(),
  realised_pnl: z.number(),
  dividends: z.number(),
  fees: z.number(),
  unpriced: z.array(z.string()),
  positions: z.array(PositionSchema),
})

// ---------------------------------------------------------------------------
// Agent result payloads. /results returns each agent's stored result as a loose
// record; panels parse it with these (safeParse) and fall back to the generic
// panel when a payload does not match, so a changed agent never breaks the page.
// ---------------------------------------------------------------------------
export const BaseAgentResultSchema = z.object({
  signal: z.string(),
  confidence: z.number(),
  reasoning: z.string(),
  summary: z.string().optional(),
  data_gaps: z.array(z.string()).optional(),
  contract_violations: z.array(z.string()).optional(),
  needs_review: z.array(z.string()).optional(),
  reused_from: z.string().nullish(),
})

export const ValuationResultSchema = BaseAgentResultSchema.extend({
  dcf: z.record(z.string(), z.number()),
  // owner_earnings_value: results stored before the company-specific valuation
  owner_earnings_value: z.number().nullable().optional(),
  earnings_power_value: z.number().nullable().optional(),
  ev_ebitda_value: z.number().nullable(),
  avg_intrinsic_value: z.number(),
  margin_of_safety: z.number(),
  market_cap: z.number(),
  // Fractions: the company's own years 1-5 growth, its discount rate, and the growth
  // the market cap implies (reverse DCF; null when no growth explains the price)
  growth_rate: z.number().optional(),
  discount_rate: z.number().optional(),
  implied_growth: z.number().nullable().optional(),
})

export const TechnicalsResultSchema = BaseAgentResultSchema.extend({
  strategies: z.record(z.string(), z.number()),
  composite: z.number(),
})

export const FundamentalsResultSchema = BaseAgentResultSchema.extend({
  factors: z.array(
    z.object({ name: z.string(), signal: z.string(), score: z.number(), detail: z.string() }),
  ),
})

export const EarningsResultSchema = BaseAgentResultSchema.extend({
  quarters_analyzed: z.number(),
  beat_rate: z.number(),
  avg_surprise_pct: z.number(),
  next_earnings: z.string(),
})

export const RiskResultSchema = BaseAgentResultSchema.extend({
  // null: not reported — shown as "N/A", never as 0
  debt_to_equity: z.number().nullable(),
  current_ratio: z.number().nullable(),
  beta: z.number().nullable(),
  risk_keywords: z.array(z.string()).optional(),
})

const SentimentComponentSchema = z.object({
  signal: z.string(),
  confidence: z.number(),
  detail: z.string(),
})

export const SentimentResultSchema = BaseAgentResultSchema.extend({
  insider: SentimentComponentSchema,
  news: SentimentComponentSchema,
})

// Yearly growth as fractions (0.137 = 13.7% a year)
export const FinancialHistoryResultSchema = BaseAgentResultSchema.extend({
  revenue_cagr: z.number(),
  net_income_cagr: z.number(),
  fcf_cagr: z.number(),
})

export const MoatResultSchema = BaseAgentResultSchema.extend({
  avg_gross_margin: z.number(),
  gross_margin_variance: z.number(),
  intangibles_pct: z.number(),
  moat_keywords: z.array(z.string()),
})

export const InstitutionalResultSchema = BaseAgentResultSchema.extend({
  // null: not reported — shown as "N/A", never as 0
  institutional_pct: z.number().nullable(),
  net_share_change: z.number().nullable(),
  direction: z.string(),
  top5_concentration: z.number().nullable(),
})

export const GrowthResultSchema = BaseAgentResultSchema.extend({
  analyst_coverage: z.number(),
  transcript_available: z.boolean(),
  earnings_release_used: z.boolean().optional(),
})

export const BroadAnalysisResultSchema = BaseAgentResultSchema.extend({
  company_name: z.string(),
  sector: z.string(),
  industry: z.string(),
  market_cap_b: z.number().nullable(),
})

export const MarketScanResultSchema = BaseAgentResultSchema.extend({
  observations: z.array(z.string()),
  risk_level: z.string(),
  metrics: z.record(z.string(), z.number().nullable()),
})

export const OutcomeReviewResultSchema = BaseAgentResultSchema.extend({
  lessons: z.array(
    z.object({
      decision_date: z.string(),
      signal: z.string(),
      horizon_days: z.number(),
      benchmark: z.string(),
      alpha: z.number(),
      hit: z.boolean(),
      text: z.string(),
    }),
  ),
})

export type Signal = z.infer<typeof SignalSchema>
export type Action = z.infer<typeof ActionSchema>
export type RunStatus = z.infer<typeof RunStatusSchema>
export type Contribution = z.infer<typeof ContributionSchema>
export type Compliance = z.infer<typeof ComplianceSchema>
export type ComplianceStatus = z.infer<typeof ComplianceStatusSchema>
export type ComplianceFinding = z.infer<typeof ComplianceFindingSchema>
export type Recommendation = z.infer<typeof RecommendationSchema>
export type SymbolOverview = z.infer<typeof SymbolOverviewSchema>
export type AgentInfo = z.infer<typeof AgentInfoSchema>
export type AgentResult = z.infer<typeof AgentResultSchema>
export type AgentRun = z.infer<typeof AgentRunSchema>
export type PipelineRunAccepted = z.infer<typeof PipelineRunAcceptedSchema>
export type PipelineRunRequest = Schemas["PipelineRunRequest"]
export type UsageGroup = z.infer<typeof UsageGroupSchema>
export type LLMCall = z.infer<typeof LLMCallSchema>
export type LLMUsageRow = z.infer<typeof LLMUsageRowSchema>
export type LLMUsageReport = z.infer<typeof LLMUsageReportSchema>
export type LLMProvider = z.infer<typeof LLMProviderSchema>
export type TrackStats = z.infer<typeof TrackStatsSchema>
export type TrackGroup = z.infer<typeof TrackGroupSchema>
export type AgentTrackRecord = z.infer<typeof AgentTrackRecordSchema>
export type TrackRecordReport = z.infer<typeof TrackRecordReportSchema>
export type OutcomeCall = z.infer<typeof OutcomeCallSchema>
export type SymbolTrackRecord = z.infer<typeof SymbolTrackRecordSchema>
export type PriceRange = z.infer<typeof PriceRangeSchema>
export type WatchlistItem = z.infer<typeof WatchlistItemSchema>
export type PriceBar = z.infer<typeof PriceBarSchema>
export type PriceHistory = z.infer<typeof PriceHistorySchema>
export type TransactionKind = z.infer<typeof TransactionKindSchema>
export type Transaction = z.infer<typeof TransactionSchema>
export type TransactionIn = Schemas["TransactionIn"]
export type Position = z.infer<typeof PositionSchema>
export type Portfolio = z.infer<typeof PortfolioSchema>
export type BaseAgentResult = z.infer<typeof BaseAgentResultSchema>
export type ValuationResult = z.infer<typeof ValuationResultSchema>
export type TechnicalsResult = z.infer<typeof TechnicalsResultSchema>
export type FundamentalsResult = z.infer<typeof FundamentalsResultSchema>
export type EarningsResult = z.infer<typeof EarningsResultSchema>
export type RiskResult = z.infer<typeof RiskResultSchema>
export type SentimentResult = z.infer<typeof SentimentResultSchema>

// ---------------------------------------------------------------------------
// Compile-time contract checks: Zod schema type === generated OpenAPI type
// ---------------------------------------------------------------------------
type Exact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false
type Assert<T extends true> = T

export type ContractChecks = [
  Assert<Exact<Contribution, Schemas["ContributionView"]>>,
  Assert<Exact<Compliance, Schemas["ComplianceView"]>>,
  Assert<Exact<ComplianceFinding, Schemas["ComplianceFindingView"]>>,
  Assert<Exact<Recommendation, Schemas["Recommendation"]>>,
  Assert<Exact<SymbolOverview, Schemas["SymbolOverview"]>>,
  Assert<Exact<AgentInfo, Schemas["AgentInfo"]>>,
  Assert<Exact<AgentResult, Schemas["AgentResultOut"]>>,
  Assert<Exact<AgentRun, Schemas["AgentRunOut"]>>,
  Assert<Exact<PipelineRunAccepted, Schemas["PipelineRunAccepted"]>>,
  Assert<Exact<LLMCall, Schemas["LLMCallOut"]>>,
  Assert<Exact<LLMUsageRow, Schemas["LLMUsageRow"]>>,
  Assert<Exact<LLMUsageReport, Schemas["LLMUsageReport"]>>,
  Assert<Exact<LLMProvider, Schemas["LLMProviderOut"]>>,
  Assert<Exact<TrackStats, Schemas["TrackStatsOut"]>>,
  Assert<Exact<TrackGroup, Schemas["TrackGroupOut"]>>,
  Assert<Exact<AgentTrackRecord, Schemas["AgentTrackRecord"]>>,
  Assert<Exact<TrackRecordReport, Schemas["TrackRecordReport"]>>,
  Assert<Exact<OutcomeCall, Schemas["OutcomeCallOut"]>>,
  Assert<Exact<SymbolTrackRecord, Schemas["SymbolTrackRecord"]>>,
  Assert<Exact<PriceBar, Schemas["PriceBarOut"]>>,
  Assert<Exact<PriceHistory, Schemas["PriceHistory"]>>,
  Assert<Exact<WatchlistItem, Schemas["WatchlistItemOut"]>>,
  Assert<Exact<Transaction, Schemas["TransactionOut"]>>,
  Assert<Exact<Position, Schemas["PositionOut"]>>,
  Assert<Exact<Portfolio, Schemas["PortfolioOut"]>>,
]
