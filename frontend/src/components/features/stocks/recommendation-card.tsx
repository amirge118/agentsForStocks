"use client"

import { ActionBadge } from "@/components/features/stocks/action-badge"
import { SignalText } from "@/components/features/stocks/signal-text"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError } from "@/lib/api/client"
import { formatConfidence, formatDate, formatScore, toneClasses } from "@/lib/format"
import { useRecommendation } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"

import { AgentBreakdownTable } from "./agent-breakdown-table"
import { ComplianceNotice } from "./compliance-notice"

export function RecommendationCard({ symbol }: { symbol: string }) {
  const { data: rec, isPending, isError, error } = useRecommendation(symbol)

  if (isPending) {
    return <Skeleton className="h-64 w-full rounded-xl" aria-label="Loading recommendation" />
  }

  if (isError) {
    const notYet = error instanceof ApiError && error.status === 404
    return (
      <Card role={notYet ? "status" : "alert"}>
        <CardContent className="p-6 text-sm">
          {notYet ? (
            <span className="text-zinc-400">No recommendation for {symbol} yet — run the analysis.</span>
          ) : (
            <span className="text-red-400">Could not load the recommendation: {error.message}</span>
          )}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-3 text-xl">
            <span className="font-mono">{rec.symbol}</span>
            <ActionBadge action={rec.action} />
          </CardTitle>
          <CardDescription>As of {formatDate(rec.run_date)}</CardDescription>
        </div>
        <dl className="grid grid-cols-3 gap-6 text-right text-sm">
          <div>
            <dt className="text-zinc-400">Score</dt>
            <dd className={cn("font-mono", toneClasses(rec.weighted_score).split(" ")[0])}>
              {formatScore(rec.weighted_score)}
            </dd>
          </div>
          <div>
            <dt className="text-zinc-400">Confidence</dt>
            <dd className="font-mono">{formatConfidence(rec.confidence)}</dd>
          </div>
          <div>
            <dt className="text-zinc-400">Signal</dt>
            <dd>
              <SignalText signal={rec.signal} />
            </dd>
          </div>
        </dl>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">{rec.reasoning}</p>
        {rec.risk_override_applied && (
          <p className="rounded-md bg-red-400/10 px-3 py-2 text-sm text-red-400">
            Risk override applied: a high-confidence bearish risk signal capped this call.
          </p>
        )}
        {rec.agents_missing.length > 0 && (
          <p className="text-sm text-zinc-400">Missing analysts: {rec.agents_missing.join(", ")}</p>
        )}
        <AgentBreakdownTable breakdown={rec.agent_breakdown} />
        <ComplianceNotice compliance={rec.compliance} disclaimer={rec.disclaimer} />
      </CardContent>
    </Card>
  )
}
