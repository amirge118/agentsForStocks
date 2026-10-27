/**
 * Data access, one repository per domain (repository pattern). Hooks depend on
 * these interfaces, so tests can substitute in-memory implementations.
 */
import { z } from "zod"

import {
  AgentInfoSchema,
  AgentResultSchema,
  AgentRunSchema,
  LLMCallSchema,
  LLMProviderSchema,
  LLMUsageReportSchema,
  PipelineRunAcceptedSchema,
  PriceHistorySchema,
  RecommendationSchema,
  SymbolOverviewSchema,
  WatchlistItemSchema,
  type AgentInfo,
  type AgentResult,
  type AgentRun,
  type LLMCall,
  type LLMProvider,
  type LLMUsageReport,
  type PipelineRunAccepted,
  type PipelineRunRequest,
  type PriceHistory,
  type PriceRange,
  type Recommendation,
  type RunStatus,
  type SymbolOverview,
  type UsageGroup,
  type WatchlistItem,
} from "@/types/api"

import { del, get, post, put } from "./client"

export interface SymbolRepository {
  getAll(): Promise<SymbolOverview[]>
  getRecommendation(symbol: string): Promise<Recommendation>
  getResults(symbol: string, filters?: { agent?: string; runDate?: string; limit?: number }): Promise<AgentResult[]>
  getPrices(symbol: string, range: PriceRange): Promise<PriceHistory>
}

export interface WatchlistRepository {
  getAll(): Promise<WatchlistItem[]>
  add(symbol: string): Promise<WatchlistItem>
  remove(symbol: string): Promise<void>
  reorder(symbols: string[]): Promise<WatchlistItem[]>
}

export interface AgentRepository {
  getAll(): Promise<AgentInfo[]>
}

export interface RunFilters {
  symbol?: string
  status?: RunStatus
  pipelineRunId?: string
  limit?: number
}

export interface RunRepository {
  getAll(filters?: RunFilters): Promise<AgentRun[]>
  create(request: PipelineRunRequest): Promise<PipelineRunAccepted>
}

export interface LLMRepository {
  getUsage(days: number, groupBy: UsageGroup): Promise<LLMUsageReport>
  getRunCalls(runId: string): Promise<LLMCall[]>
  getProviders(): Promise<LLMProvider[]>
}

export const symbolRepository: SymbolRepository = {
  getAll: () => get("/symbols", z.array(SymbolOverviewSchema)),
  getRecommendation: (symbol) =>
    get(`/symbols/${encodeURIComponent(symbol)}/recommendation`, RecommendationSchema),
  getResults: (symbol, filters = {}) =>
    get(`/symbols/${encodeURIComponent(symbol)}/results`, z.array(AgentResultSchema), {
      agent: filters.agent,
      run_date: filters.runDate,
      limit: filters.limit,
    }),
  getPrices: (symbol, range) =>
    get(`/symbols/${encodeURIComponent(symbol)}/prices`, PriceHistorySchema, { range }),
}

export const watchlistRepository: WatchlistRepository = {
  getAll: () => get("/watchlist", z.array(WatchlistItemSchema)),
  add: (symbol) => post("/watchlist", WatchlistItemSchema, { symbol }),
  remove: (symbol) => del(`/watchlist/${encodeURIComponent(symbol)}`, z.undefined()),
  reorder: (symbols) => put("/watchlist/order", z.array(WatchlistItemSchema), { symbols }),
}

export const agentRepository: AgentRepository = {
  getAll: () => get("/agents", z.array(AgentInfoSchema)),
}

export const runRepository: RunRepository = {
  getAll: (filters = {}) =>
    get("/runs", z.array(AgentRunSchema), {
      symbol: filters.symbol,
      status: filters.status,
      pipeline_run_id: filters.pipelineRunId,
      limit: filters.limit,
    }),
  create: (request) => post("/pipeline/runs", PipelineRunAcceptedSchema, request),
}

export const llmRepository: LLMRepository = {
  getUsage: (days, groupBy) =>
    get("/llm/usage", LLMUsageReportSchema, { days, group_by: groupBy }),
  getRunCalls: (runId) =>
    get(`/runs/${encodeURIComponent(runId)}/llm-calls`, z.array(LLMCallSchema)),
  getProviders: () => get("/llm/providers", z.array(LLMProviderSchema)),
}
