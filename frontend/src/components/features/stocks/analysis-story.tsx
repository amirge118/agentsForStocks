"use client"

import Link from "next/link"
import { useEffect, useRef, useState, type RefObject } from "react"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { ApiError } from "@/lib/api/client"
import { consensus, runningScore, type RunningStep } from "@/lib/charts"
import { formatConfidence, formatDate, formatScore, toneClasses } from "@/lib/format"
import { useAgentResults, useAgents, useRecommendation } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import { BaseAgentResultSchema, type AgentResult } from "@/types/api"

import { AgentDetail } from "./agent-panels/variants"
import { ScoreScale } from "./score-scale"

const TONE: Record<string, string> = { bullish: "text-ok", bearish: "text-bad", neutral: "text-ink-2" }
const ACTION_TONE = { BUY: "text-ok", SELL: "text-bad", HOLD: "text-ink" } as const

/**
 * The analysis as a scroll: the question, one analyst per screen, then the verdict.
 * scroll-craft rules: motion is transform / opacity only, content is visible without it
 * (the reveal is a CSS scroll timeline, skipped under reduced motion), every number is real.
 */
export function AnalysisStory({ symbol }: { symbol: string }) {
  const rec = useRecommendation(symbol)
  const results = useAgentResults(symbol)
  const agents = useAgents()
  const articleRef = useRef<HTMLElement>(null)
  const actCount = results.data ? results.data.size : 0
  const active = useActiveAct(articleRef, actCount)

  if (rec.isPending || results.isPending) return <Loading label="Loading the analysis" className="h-[60vh]" />
  if (rec.isError) {
    return rec.error instanceof ApiError && rec.error.status === 404 ? (
      <Empty>
        No recommendation for {symbol} yet, so there is no story to tell.{" "}
        <Link href={`/symbols/${symbol}`} className="text-ink underline decoration-rule-2 hover:text-accent">
          Back to {symbol}
        </Link>
      </Empty>
    ) : (
      <LoadError what="the recommendation" error={rec.error} />
    )
  }
  if (results.isError) return <LoadError what="the agent results" error={results.error} />

  const order = agents.data?.map((a) => a.name) ?? []
  const rank = (agent: string) => (order.indexOf(agent) === -1 ? order.length : order.indexOf(agent))
  const rows = [...results.data.values()]
    .filter((r) => r.agent_type !== "recommendation")
    .sort((a, b) => rank(a.agent_type) - rank(b.agent_type))
  const counts = consensus(rec.data.agent_breakdown)
  const v = rec.data
  const steps = runningScore(
    rows.map((r) => r.agent_type),
    v.agent_breakdown,
  )

  return (
    <article ref={articleRef} aria-label={`${symbol} analysis story`} className="story">
      <div className="story-progress" aria-hidden />
      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-12">
        <div>
          <section data-act={-1} className="story-act flex min-h-[70vh] flex-col justify-center gap-6">
            <p className="text-sm text-muted">As of {formatDate(v.run_date)}</p>
            <h1 className="max-w-[18ch] text-4xl leading-tight sm:text-6xl">
              BUY, SELL or HOLD for <span className="font-mono">{symbol}</span>?
            </h1>
            <p className="max-w-prose text-lg text-ink-2">
              {rows.length} analysts read the numbers, the filings and the news. Here is what each one found, one at a
              time, before the verdict they add up to.
            </p>
            <p className="text-sm text-muted">Scroll to read on.</p>
          </section>

          {rows.map((row, i) => (
            <AnalystAct key={row.agent_type} row={row} index={i + 1} total={rows.length} step={steps[i]!} />
          ))}

          {counts.bullish > 0 && counts.bearish > 0 && (
            <section className="story-act flex min-h-[60vh] flex-col justify-center gap-4">
              <h2 className="text-3xl">They don’t all agree.</h2>
              <p className="max-w-prose text-lg text-ink-2">
                <span className="font-mono text-ok">{counts.bullish}</span> bullish,{" "}
                <span className="font-mono text-bad">{counts.bearish}</span> bearish,{" "}
                <span className="font-mono">{counts.neutral}</span> neutral. Each one counts by its weight and its
                confidence, so the louder analysts are not always the ones that decide.
              </p>
            </section>
          )}

          <section data-act={rows.length} aria-label="The verdict" className="story-act story-peak flex min-h-[90vh] flex-col justify-center gap-8">
            <p className="text-sm text-muted">The verdict</p>
            <p className={cn("font-mono text-7xl leading-none tracking-tight sm:text-9xl", ACTION_TONE[v.action])}>
              {v.action}
            </p>
            <div className="grid max-w-xl gap-6 sm:grid-cols-[auto_1fr] sm:items-end">
              <dl className="flex gap-8">
                <div>
                  <dt className="text-xs text-muted">Score</dt>
                  <dd className="font-mono text-2xl">{formatScore(v.weighted_score)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Confidence</dt>
                  <dd className="font-mono text-2xl">{formatConfidence(v.confidence)}</dd>
                </div>
              </dl>
              <ScoreScale score={v.weighted_score} />
            </div>
            <p className="max-w-prose text-lg text-ink-2">{v.reasoning}</p>
            {v.risk_override_applied && (
              <p className="max-w-prose text-sm text-bad">A high-confidence bearish risk signal capped this call.</p>
            )}
          </section>
        </div>

        <RunningScoreAside steps={steps} active={active ?? rows.length} />
      </div>

      <footer className="space-y-4 border-t border-rule py-10">
        <p className="max-w-prose text-xs text-muted">{v.disclaimer}</p>
        <Link
          href={`/symbols/${symbol}`}
          className="inline-flex rounded-control border border-rule-2 bg-paper-2 px-4 py-2 text-sm hover:bg-paper-3"
        >
          See every figure for {symbol}
        </Link>
      </footer>
    </article>
  )
}

function AnalystAct({ row, index, total, step }: { row: AgentResult; index: number; total: number; step: RunningStep }) {
  const base = BaseAgentResultSchema.safeParse(row.result)
  const name = row.agent_type.replace(/_/g, " ")
  return (
    <section data-act={index - 1} aria-label={`${name}, analyst ${index} of ${total}`} className="story-act flex min-h-[80vh] flex-col justify-center gap-6">
      <p className="text-sm text-muted">
        Analyst <span className="font-mono">{index}</span> of <span className="font-mono">{total}</span>
      </p>
      <h2 className="text-3xl capitalize sm:text-4xl">{name}</h2>
      {base.success ? (
        <>
          <p className={cn("text-2xl", TONE[base.data.signal] ?? "text-muted")}>
            <span className="capitalize">{base.data.signal}</span>{" "}
            <span className="text-base text-muted">
              <span className="font-mono">{formatConfidence(base.data.confidence)}</span> sure
            </span>
          </p>
          <ScoreLine step={step} />
          <div className="flex max-w-xl flex-col gap-4 rounded-card border border-rule bg-paper-2 p-5 empty:hidden">
            <AgentDetail agent={row.agent_type} result={row.result} />
          </div>
          <p className="max-w-prose text-lg text-ink-2">{base.data.reasoning}</p>
          {(base.data.data_gaps?.length ?? 0) > 0 && (
            <p className="text-sm text-muted">It worked without: {base.data.data_gaps!.join(", ")}.</p>
          )}
        </>
      ) : (
        <p className="text-muted">This analyst’s result has an unexpected shape and can’t be shown.</p>
      )}
    </section>
  )
}

/** What this analyst did to the score, and where it stands after them. */
function ScoreLine({ step }: { step: RunningStep }) {
  if (step.contribution === null) return <p className="text-sm text-muted">Not counted in the score.</p>
  return (
    <p className="text-sm text-ink-2">
      Counts{" "}
      <span className={cn("rounded-chip px-1 font-mono", toneClasses(step.contribution))}>
        {formatScore(step.contribution)}
      </span>
      ; the score is now <span className="font-mono text-ink">{formatScore(step.total)}</span>.
    </p>
  )
}

/**
 * On wide screens: the score as it builds, beside the act being read. Only the number
 * and the marker change (no animation). Before the first act it is 0; at the verdict
 * and without JS, the full total.
 */
function RunningScoreAside({ steps, active }: { steps: RunningStep[]; active: number }) {
  const shown = Math.min(active, steps.length - 1)
  const total = shown < 0 ? 0 : steps[shown]!.total
  return (
    <aside aria-label="Running score" className="hidden lg:block">
      <div className="sticky top-20 mt-[15vh] space-y-4 rounded-card border border-rule bg-paper-2 p-4">
        <p className="text-sm text-muted">Running score</p>
        <p aria-live="polite" className="font-mono text-3xl">
          {formatScore(total)}
        </p>
        <ScoreScale score={total} label="Running score" />
        <ol className="space-y-1 text-sm">
          {steps.map((s, i) => (
            <li key={s.agent} className={cn("flex justify-between gap-2", i > shown ? "text-muted" : "text-ink-2")}>
              <span className="capitalize">{s.agent.replace(/_/g, " ")}</span>
              {i <= shown && (
                s.contribution === null ? (
                  <span className="text-muted">not counted</span>
                ) : (
                  <span className={cn("rounded-chip px-1 font-mono", toneClasses(s.contribution))}>
                    {formatScore(s.contribution)}
                  </span>
                )
              )}
            </li>
          ))}
        </ol>
      </div>
    </aside>
  )
}

/**
 * Which act is in the middle of the screen: -1 the opening, 0..n-1 the analysts,
 * n the verdict. null until the observer reports (and without IntersectionObserver).
 */
function useActiveAct(ref: RefObject<HTMLElement | null>, count: number): number | null {
  const [active, setActive] = useState<number | null>(null)
  useEffect(() => {
    const root = ref.current
    if (!root || typeof IntersectionObserver === "undefined") return
    const observer = new IntersectionObserver(
      (entries) => {
        const hit = entries.find((e) => e.isIntersecting)
        if (hit) setActive(Number((hit.target as HTMLElement).dataset.act))
      },
      { rootMargin: "-45% 0px -45% 0px" },
    )
    root.querySelectorAll("[data-act]").forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [ref, count])
  return active
}
