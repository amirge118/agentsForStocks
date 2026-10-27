"use client"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { formatConfidence, formatDate } from "@/lib/format"
import { useAgentResults, useAgents } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import { BaseAgentResultSchema, type AgentResult } from "@/types/api"

import { AgentDetail } from "./agent-panels/variants"

const ARROW: Record<string, string> = { bullish: "▲", bearish: "▼", neutral: "■" }
const TONE: Record<string, string> = { bullish: "text-ok", bearish: "text-bad", neutral: "text-ink-2" }

/**
 * One panel per analyst with its latest stored result, in pipeline order. The
 * recommendation itself is the hero above, so it has no panel here.
 */
export function AgentPanels({ symbol }: { symbol: string }) {
  const results = useAgentResults(symbol)
  const agents = useAgents()

  if (results.isPending) return <Loading label="Loading agent results" className="h-72" />
  if (results.isError) return <LoadError what="the agent results" error={results.error} />

  const order = agents.data?.map((a) => a.name) ?? []
  const descriptions = new Map(agents.data?.map((a) => [a.name, a.description]) ?? [])
  const rows = [...results.data.values()]
    .filter((r) => r.agent_type !== "recommendation")
    .sort((a, b) => rank(order, a.agent_type) - rank(order, b.agent_type))

  if (rows.length === 0) return <Empty>No agent has analysed {symbol} yet.</Empty>

  return (
    <section aria-labelledby="agent-panels-title" className="space-y-3">
      <h2 id="agent-panels-title" className="text-base">
        What each analyst found
      </h2>
      {/* 1px seams from each panel's outline, clipped at the frame, so a short last row leaves no hole */}
      <div className="grid overflow-hidden rounded-card border border-rule bg-paper-2 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => (
          <AgentPanel key={row.agent_type} row={row} description={descriptions.get(row.agent_type)} />
        ))}
      </div>
    </section>
  )
}

function rank(order: string[], agent: string): number {
  const i = order.indexOf(agent)
  return i === -1 ? order.length : i
}

function AgentPanel({ row, description }: { row: AgentResult; description?: string }) {
  const base = BaseAgentResultSchema.safeParse(row.result)
  const name = row.agent_type.replace(/_/g, " ")
  return (
    <article aria-label={`${name} analysis`} className="flex flex-col gap-3 bg-paper-2 p-4 outline outline-1 outline-rule">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm capitalize">{name}</h3>
          {description && <p className="truncate text-xs text-muted">{description}</p>}
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
          <AgentDetail agent={row.agent_type} result={row.result} />
          {base.data.reasoning && (
            <details className="group text-sm">
              <summary className="cursor-pointer text-xs text-muted hover:text-ink">Reasoning</summary>
              <p className="mt-2 text-ink-2">{base.data.reasoning}</p>
            </details>
          )}
          {(base.data.data_gaps?.length ?? 0) > 0 && (
            <p className="text-xs text-muted">No data from: {base.data.data_gaps!.join(", ")}</p>
          )}
        </>
      ) : (
        <p className="text-sm text-muted">This result has an unexpected shape and can&apos;t be shown.</p>
      )}
      <p className="mt-auto text-xs text-muted">As of {formatDate(row.run_date)}</p>
    </article>
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
      <span className="font-mono text-xs text-ink-2">{formatConfidence(value)}</span>
    </div>
  )
}
