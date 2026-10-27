"use client"

/** TanStack Query v5 hooks — the only way components read or change server data. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useRepositories } from "@/lib/api/repository-context"
import type { RunFilters } from "@/lib/api/repositories"
import { toast } from "@/lib/hooks/use-toast"
import type { AgentResult, PipelineRunRequest, PriceRange, UsageGroup } from "@/types/api"

export const queryKeys = {
  symbols: ["symbols"] as const,
  agents: ["agents"] as const,
  recommendation: (symbol: string) => ["symbols", symbol, "recommendation"] as const,
  runs: (filters: RunFilters) => ["runs", filters] as const,
  llmUsage: (days: number, groupBy: UsageGroup) => ["llm", "usage", days, groupBy] as const,
  runLLMCalls: (runId: string) => ["llm", "runs", runId] as const,
  llmProviders: ["llm", "providers"] as const,
  agentResults: (symbol: string) => ["symbols", symbol, "results"] as const,
  scoreHistory: (symbol: string) => ["symbols", symbol, "results", "recommendation"] as const,
  prices: (symbol: string, range: PriceRange) => ["symbols", symbol, "prices", range] as const,
}

/** The newest stored result of each agent (rows arrive newest first). */
export function latestPerAgent(rows: AgentResult[]): Map<string, AgentResult> {
  const latest = new Map<string, AgentResult>()
  for (const row of rows) if (!latest.has(row.agent_type)) latest.set(row.agent_type, row)
  return latest
}

export function useSymbols() {
  const { symbols } = useRepositories()
  return useQuery({ queryKey: queryKeys.symbols, queryFn: () => symbols.getAll() })
}

export function useAgents() {
  const { agents } = useRepositories()
  return useQuery({ queryKey: queryKeys.agents, queryFn: () => agents.getAll() })
}

export function useRecommendation(symbol: string) {
  const { symbols } = useRepositories()
  return useQuery({
    queryKey: queryKeys.recommendation(symbol),
    queryFn: () => symbols.getRecommendation(symbol),
  })
}

export function useAgentResults(symbol: string) {
  const { symbols } = useRepositories()
  return useQuery({
    queryKey: queryKeys.agentResults(symbol),
    queryFn: () => symbols.getResults(symbol, { limit: 200 }),
    select: latestPerAgent,
  })
}

/** Recommendation results over time, oldest first (one row per market day). */
export function useScoreHistory(symbol: string) {
  const { symbols } = useRepositories()
  return useQuery({
    queryKey: queryKeys.scoreHistory(symbol),
    queryFn: () => symbols.getResults(symbol, { agent: "recommendation", limit: 250 }),
    select: (rows: AgentResult[]) => [...rows].sort((a, b) => a.run_date.localeCompare(b.run_date)),
  })
}

export function usePrices(symbol: string, range: PriceRange) {
  const { symbols } = useRepositories()
  return useQuery({
    queryKey: queryKeys.prices(symbol, range),
    queryFn: () => symbols.getPrices(symbol, range),
    retry: false, // a 502 means the provider is down; the panel says so instead of spinning
  })
}

export function useRuns(filters: RunFilters = {}) {
  const { runs } = useRepositories()
  return useQuery({
    queryKey: queryKeys.runs(filters),
    queryFn: () => runs.getAll(filters),
    refetchInterval: 10_000, // runs progress in the background
  })
}

export function useLLMUsage(days: number, groupBy: UsageGroup) {
  const { llm } = useRepositories()
  return useQuery({
    queryKey: queryKeys.llmUsage(days, groupBy),
    queryFn: () => llm.getUsage(days, groupBy),
  })
}

export function useRunLLMCalls(runId: string) {
  const { llm } = useRepositories()
  return useQuery({
    queryKey: queryKeys.runLLMCalls(runId),
    queryFn: () => llm.getRunCalls(runId),
  })
}

export function useLLMProviders() {
  const { llm } = useRepositories()
  return useQuery({ queryKey: queryKeys.llmProviders, queryFn: () => llm.getProviders() })
}

/**
 * Add / remove / reorder watchlist symbols. Each change refreshes the overview the
 * watchlist table renders; failures surface as a destructive toast.
 */
export function useWatchlistMutations() {
  const { watchlist } = useRepositories()
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.symbols })
  const fail = (title: string) => (error: Error) => toast({ variant: "destructive", title, description: error.message })
  return {
    add: useMutation({
      mutationFn: (symbol: string) => watchlist.add(symbol),
      onSuccess: async (item) => {
        await refresh()
        toast({ title: `${item.symbol} added`, description: "It is analysed in the next daily run, or run it now." })
      },
      onError: fail("Could not add the symbol"),
    }),
    remove: useMutation({
      mutationFn: (symbol: string) => watchlist.remove(symbol),
      onSuccess: refresh,
      onError: fail("Could not remove the symbol"),
    }),
    reorder: useMutation({
      mutationFn: (symbols: string[]) => watchlist.reorder(symbols),
      onSuccess: refresh,
      onError: fail("Could not reorder the watchlist"),
    }),
  }
}

export function useStartPipelineRun() {
  const { runs } = useRepositories()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: PipelineRunRequest) => runs.create(request),
    onSuccess: async (accepted) => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] })
      await queryClient.invalidateQueries({ queryKey: ["llm"] })
      await queryClient.invalidateQueries({ queryKey: queryKeys.symbols })
      toast({
        title: "Pipeline started",
        description: `${accepted.symbols.length} symbols · ${accepted.agents.length} agents`,
      })
    },
    onError: (error) => {
      toast({ variant: "destructive", title: "Could not start pipeline", description: error.message })
    },
  })
}
