"use client"

/** TanStack Query v5 hooks — the only way components read or change server data. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useRepositories } from "@/lib/api/repository-context"
import type { RunFilters } from "@/lib/api/repositories"
import { toast } from "@/lib/hooks/use-toast"
import type { PipelineRunRequest, UsageGroup } from "@/types/api"

export const queryKeys = {
  symbols: ["symbols"] as const,
  recommendation: (symbol: string) => ["symbols", symbol, "recommendation"] as const,
  runs: (filters: RunFilters) => ["runs", filters] as const,
  llmUsage: (days: number, groupBy: UsageGroup) => ["llm", "usage", days, groupBy] as const,
  runLLMCalls: (runId: string) => ["llm", "runs", runId] as const,
}

export function useSymbols() {
  const { symbols } = useRepositories()
  return useQuery({ queryKey: queryKeys.symbols, queryFn: () => symbols.getAll() })
}

export function useRecommendation(symbol: string) {
  const { symbols } = useRepositories()
  return useQuery({
    queryKey: queryKeys.recommendation(symbol),
    queryFn: () => symbols.getRecommendation(symbol),
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
