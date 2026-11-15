"use client"

import Link from "next/link"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { ActionBadge } from "@/components/features/stocks/action-badge"
import { formatCurrency, formatDate, formatShare } from "@/lib/format"
import { useExposure } from "@/lib/hooks/queries"
import { ActionSchema } from "@/types/api"

const BAR: Record<string, string> = { BUY: "bg-ok", HOLD: "bg-ink-2", SELL: "bg-bad" }

/** How much of the portfolio sits under each of the agents' calls, and what changed. */
export function AgentsOnPortfolio() {
  const { data, isPending, isError, error } = useExposure()
  if (isPending) return <Loading label="Loading the agents' view" className="h-40" />
  if (isError) return <LoadError what="the agents' view" error={error} />
  const { actions, changed } = data
  if (actions.length === 0) {
    return <p className="text-sm text-muted">The agents&apos; view appears once the portfolio holds something.</p>
  }
  const sell = actions.find((a) => a.action === "SELL")

  return (
    <div className="space-y-4">
      <div
        role="img"
        aria-label={actions.map((a) => `${a.action} ${formatShare(a.weight)}`).join(", ")}
        className="flex h-2 overflow-hidden rounded-chip bg-paper-3"
      >
        {actions.map((a) => (
          <div key={a.action} className={BAR[a.action] ?? "bg-rule-2"} style={{ width: `${a.weight}%` }} />
        ))}
      </div>
      <p className="text-xs text-muted">
        The rest of the bar is cash (
        <span className="font-mono">{formatShare(Math.max(0, 100 - actions.reduce((sum, a) => sum + a.weight, 0)))}</span>
        ).
      </p>
      <ul className="space-y-2 text-sm">
        {actions.map((a) => {
          const action = ActionSchema.safeParse(a.action)
          return (
            <li key={a.action} className="flex items-start justify-between gap-3">
              <span className="flex min-w-0 flex-wrap items-center gap-2">
                {action.success ? <ActionBadge action={action.data} /> : <span className="text-muted">{a.action}</span>}
                <span className="truncate font-mono text-xs text-ink-2">{a.symbols.join(", ")}</span>
              </span>
              <span className="shrink-0 text-right">
                <span className="font-mono tabular-nums">{formatShare(a.weight)}</span>
                <span className="block font-mono text-xs text-muted">{formatCurrency(a.value)}</span>
              </span>
            </li>
          )
        })}
      </ul>
      {sell && (
        <p className="rounded-control border border-rule bg-bad-soft px-3 py-2 text-xs text-ink">
          The agents rate <span className="font-mono">{sell.symbols.join(", ")}</span> SELL:{" "}
          <span className="font-mono">{formatShare(sell.weight)}</span> of the portfolio. Open each to read why.
        </p>
      )}
      <section aria-label="Calls that changed" className="space-y-1.5">
        <h3 className="text-xs text-muted">Changed at the last run</h3>
        {changed.length === 0 ? (
          <p className="text-sm text-muted">No holding&apos;s call changed.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {changed.map((c) => (
              <li key={c.symbol} className="flex flex-wrap items-center gap-2">
                <Link href={`/symbols/${c.symbol}`} className="font-mono font-medium hover:underline">
                  {c.symbol}
                </Link>
                <ActionBadge action={c.previous} />
                <span aria-hidden className="text-muted">
                  →
                </span>
                <span className="sr-only">to</span>
                <ActionBadge action={c.action} />
                <span className="text-xs text-muted">{formatDate(c.run_date)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
