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
export const RunStatusSchema = z.enum(["completed", "skipped", "failed"])
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
]
