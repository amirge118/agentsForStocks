"use client"

import type { ReactNode } from "react"
import { z } from "zod"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { formatConfidence, formatDate, formatScore } from "@/lib/format"
import { useAgentResults, useAgents } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import { BaseAgentResultSchema, ContributionSchema, type AgentResult, type Contribution } from "@/types/api"

import { AgentDetail } from "./agent-panels/variants"

const ARROW: Record<string, string> = { bullish: "▲", bearish: "▼", neutral: "■" }
const TONE: Record<string, string> = { bullish: "text-ok", bearish: "text-bad", neutral: "text-ink-2" }
const BreakdownSchema = z.object({ agent_breakdown: z.array(ContributionSchema) })

/**
 * One panel per analyst with its latest stored result, in pipeline order: first the
 * analysts whose signals add up to the score, then those that only give context.
 * The recommendation itself is the hero above, so it has no panel here.
 */
export function AgentPanels({ symbol }: { symbol: string }) {
  const results = useAgentResults(symbol)
  const agents = useAgents()

  if (results.isPending) return <Loading label="Loading agent results" className="h-72" />
  if (results.isError) return <LoadError what="the agent results" error={results.error} />

  const order = agents.data?.map((a) => a.name) ?? []
  const descriptions = new Map(agents.data?.map((a) => [a.name, a.description]) ?? [])
  const weights = new Map(agents.data?.map((a) => [a.name, a.recommendation_weight]) ?? [])
  const breakdown = BreakdownSchema.safeParse(results.data.get("recommendation")?.result)
  const parts = new Map(breakdown.success ? breakdown.data.agent_breakdown.map((c) => [c.agent, c]) : [])
  const rows = [...results.data.values()]
    .filter((r) => r.agent_type !== "recommendation")
    .sort((a, b) => rank(order, a.agent_type) - rank(order, b.agent_type))

  if (rows.length === 0) return <Empty>No agent has analysed {symbol} yet.</Empty>

  // Until the agent list loads every analyst counts as voting: one group, no wrong split
  const voting = rows.filter((r) => (weights.get(r.agent_type) ?? 1) > 0)
  const context = rows.filter((r) => (weights.get(r.agent_type) ?? 1) === 0)
  const panel = (row: AgentResult) => (
    <AgentPanel
      key={row.agent_type}
      row={row}
      description={descriptions.get(row.agent_type)}
      part={parts.get(row.agent_type)}
    />
  )

  return (
    <section aria-labelledby="agent-panels-title" className="space-y-3">
      <div className="space-y-1">
        <h2 id="agent-panels-title" className="text-base">
          What each analyst found
        </h2>
        <p className="text-sm text-muted">
          Each analyst reads one side of the company and gives a signal with how sure it is. A signal times its
          confidence times the analyst&apos;s weight is what it adds to the score.
        </p>
      </div>
      <PanelGroup title="Count toward the score" rows={voting} panel={panel} />
      {context.length > 0 && (
        <PanelGroup
          title="Context only"
          note="Shown to explain the picture; their signals don't change the score."
          rows={context}
          panel={panel}
        />
      )}
    </section>
  )
}

function PanelGroup({
  title,
  note,
  rows,
  panel,
}: {
  title: string
  note?: string
  rows: AgentResult[]
  panel: (row: AgentResult) => ReactNode
}) {
  if (rows.length === 0) return null
  return (
    <div className="space-y-2">
      <h3 className="text-sm text-ink-2">
        {title} <span className="font-mono text-xs text-muted">{rows.length}</span>
        {note && <span className="block text-xs text-muted">{note}</span>}
      </h3>
      {/* 1px seams from each panel's outline, clipped at the frame, so a short last row leaves no hole */}
      <div className="grid overflow-hidden rounded-card border border-rule bg-paper-2 md:grid-cols-2">
        {rows.map(panel)}
      </div>
    </div>
  )
}

function rank(order: string[], agent: string): number {
  const i = order.indexOf(agent)
  return i === -1 ? order.length : i
}

function AgentPanel({ row, description, part }: { row: AgentResult; description?: string; part?: Contribution }) {
  const base = BaseAgentResultSchema.safeParse(row.result)
  const name = row.agent_type.replace(/_/g, " ")
  return (
    <article aria-label={`${name} analysis`} className="flex flex-col gap-3 bg-paper-2 p-4 outline outline-1 outline-rule">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-sm capitalize">{name}</h4>
          {description && <p className="text-xs text-muted">{description}</p>}
        </div>
        {base.success && (
          <span className={cn("shrink-0 text-sm capitalize", TONE[base.data.signal] ?? "text-muted")}>
            <span aria-hidden className="mr-1 text-xs">
              {ARROW[base.data.signal] ?? "·"}
            </span>
            {base.data.signal}
          </span>
        )}
      </header>
      {base.success ? (
        <>
          <ConfidenceMeter value={base.data.confidence} />
          {part && part.weight > 0 && <ScorePart part={part} />}
          {base.data.reasoning && <p className="text-sm text-ink">{base.data.reasoning}</p>}
          <AgentDetail agent={row.agent_type} result={row.result} />
          <Notes
            reusedFrom={base.data.reused_from}
            gaps={base.data.data_gaps}
            review={base.data.needs_review}
            violations={base.data.contract_violations}
          />
        </>
      ) : (
        <p className="text-sm text-muted">This result has an unexpected shape and can&apos;t be shown.</p>
      )}
      <p className="mt-auto text-xs text-muted">As of {formatDate(row.run_date)}</p>
    </article>
  )
}

/** What this analyst added to today's score, out of its share of the weight. */
function ScorePart({ part }: { part: Contribution }) {
  const moved = part.contribution
  return (
    <p className="text-xs text-muted">
      Weighs <span className="font-mono text-ink-2">{part.weight}</span> of 100 in the score · added{" "}
      <span className={cn("font-mono", moved > 0 ? "text-ok" : moved < 0 ? "text-bad" : "text-ink-2")}>
        {formatScore(moved)}
      </span>
    </p>
  )
}

function Notes({
  reusedFrom,
  gaps,
  review,
  violations,
}: {
  reusedFrom?: string | null
  gaps?: string[]
  review?: string[]
  violations?: string[]
}) {
  const items: { label: string; text: string; strong?: boolean }[] = []
  if (reusedFrom) {
    items.push({
      label: "Carried over",
      text: `from ${formatDate(reusedFrom)}. It runs again after a new report, or once the result is too old`,
    })
  }
  if (gaps?.length) items.push({ label: "Missing data", text: gaps.map((g) => g.replace(/_/g, " ")).join(", ") })
  if (review?.length) items.push({ label: "Check before trusting", text: review.join("; "), strong: true })
  if (violations?.length) items.push({ label: "Rule check", text: violations.join("; "), strong: true })
  if (items.length === 0) return null
  return (
    <dl className="space-y-1 border-t border-rule pt-2 text-xs">
      {items.map((item) => (
        <div key={item.label}>
          <dt className="inline text-muted">{item.label}: </dt>
          <dd className={cn("inline", item.strong ? "text-ink-2" : "text-muted")}>{item.text}</dd>
        </div>
      ))}
    </dl>
  )
}

function ConfidenceMeter({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div
        role="meter"
        aria-label="Confidence"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value)}
        className="h-1.5 flex-1 rounded-full bg-paper-3"
      >
        <div className="h-full rounded-full bg-ink-2" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
      <span className="text-xs text-muted">
        <span className="font-mono text-ink-2">{formatConfidence(value)}</span> sure
      </span>
    </div>
  )
}
