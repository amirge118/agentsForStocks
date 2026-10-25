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

export const AgentInfoSchema = z.object({
  name: z.string(),
  description: z.string(),
  depends_on: z.array(z.string()),
  recommendation_weight: z.number(),
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
})

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
]
