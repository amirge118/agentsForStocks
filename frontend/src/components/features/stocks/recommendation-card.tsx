"use client"

import { ActionBadge } from "@/components/features/stocks/action-badge"
import { SignalText } from "@/components/features/stocks/signal-text"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError } from "@/lib/api/client"
import { isStale } from "@/lib/charts"
import { formatConfidence, formatDate, formatScore, toneClasses } from "@/lib/format"
import { useRecommendation } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"

import { AgentBreakdownTable } from "./agent-breakdown-table"
import { ComplianceNotice } from "./compliance-notice"
import { ConsensusBar } from "./consensus-bar"
import { ContributionWaterfall } from "./contribution-waterfall"
import { ScoreScale } from "./score-scale"

const ACTION_TONE = { BUY: "text-ok", SELL: "text-bad", HOLD: "text-ink" } as const

export function RecommendationCard({ symbol }: { symbol: string }) {
  const { data: rec, isPending, isError, error } = useRecommendation(symbol)

  if (isPending) {
    return <Skeleton className="h-64 w-full rounded-card" aria-label="Loading recommendation" />
  }

  if (isError) {
    const notYet = error instanceof ApiError && error.status === 404
    return (
      <Card role={notYet ? "status" : "alert"}>
        <CardContent className="p-6 text-sm">
          {notYet ? (
            <span className="text-muted">No recommendation for {symbol} yet. Run the analysis to get one.</span>
          ) : (
            <span className="text-bad">Could not load the recommendation: {error.message}</span>
          )}
        </CardContent>
      </Card>
    )
  }

  const stale = isStale(rec.run_date)
  return (
    <Card>
      <CardHeader className="gap-6 space-y-0 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <CardTitle className="flex items-center gap-3 text-xl">
            <span className="font-mono">{rec.symbol}</span>
            <ActionBadge action={rec.action} />
          </CardTitle>
          <p
            className={cn("font-mono text-5xl leading-none tracking-tight", ACTION_TONE[rec.action])}
            aria-label={`Recommendation: ${rec.action}`}
          >
            {rec.action}
          </p>
          <CardDescription className="flex items-center gap-2">
            <span>As of {formatDate(rec.run_date)}</span>
            {stale && (
              <span className="rounded-chip border border-accent/40 bg-accent-soft px-1.5 py-0.5 text-xs text-accent">
                Older than one market day
              </span>
            )}
          </CardDescription>
        </div>
        <div className="w-full space-y-4 md:max-w-sm">
          <dl className="grid grid-cols-3 gap-6 text-right text-sm">
            <div>
              <dt className="text-muted">Score</dt>
              <dd className={cn("font-mono text-lg", toneClasses(rec.weighted_score).split(" ")[0])}>
                {formatScore(rec.weighted_score)}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Confidence</dt>
              <dd className="font-mono text-lg">{formatConfidence(rec.confidence)}</dd>
            </div>
            <div>
              <dt className="text-muted">Signal</dt>
              <dd className="text-lg">
                <SignalText signal={rec.signal} />
              </dd>
            </div>
          </dl>
          <ScoreScale score={rec.weighted_score} />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <p className="max-w-prose text-base text-ink-2">{rec.reasoning}</p>
        {rec.risk_override_applied && (
          <p className="rounded-control border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad">
            Risk override applied: a high-confidence bearish risk signal capped this call.
          </p>
        )}
        <ConsensusBar breakdown={rec.agent_breakdown} />
        <ContributionWaterfall breakdown={rec.agent_breakdown} score={rec.weighted_score} />
        {rec.agents_missing.length > 0 && (
          <p className="text-sm text-muted">Missing analysts: {rec.agents_missing.join(", ")}</p>
        )}
        <AgentBreakdownTable breakdown={rec.agent_breakdown} />
        <ComplianceNotice compliance={rec.compliance} disclaimer={rec.disclaimer} />
      </CardContent>
    </Card>
  )
}
