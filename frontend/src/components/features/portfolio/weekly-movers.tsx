"use client"

import Link from "next/link"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { ActionBadge } from "@/components/features/stocks/action-badge"
import { formatDate, formatPercent, formatSignedCurrency } from "@/lib/format"
import { usePerformance, useSymbols } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import type { Mover, Recommendation } from "@/types/api"

/** The week's three biggest gainers and losers among the holdings, with the agents' call. */
export function WeeklyMovers() {
  const performance = usePerformance()
  const symbols = useSymbols()

  if (performance.isPending) return <Loading label="Loading this week's movers" className="h-32" />
  if (performance.isError) return <LoadError what="this week's movers" error={performance.error} />
  const { gainers, losers, week_start } = performance.data
  const calls = new Map(symbols.data?.map((s) => [s.symbol, s.recommendation]) ?? [])

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        {week_start ? `Since the close of ${formatDate(week_start)}` : "Since each came in this week"}, for the shares
        held now.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <MoverList title="Gainers" movers={gainers} calls={calls} none="Nothing up this week." />
        <MoverList title="Losers" movers={losers} calls={calls} none="Nothing down this week." />
      </div>
    </div>
  )
}

function MoverList({
  title,
  movers,
  calls,
  none,
}: {
  title: string
  movers: Mover[]
  calls: Map<string, Recommendation | null>
  none: string
}) {
  return (
    <section aria-label={title} className="space-y-1.5">
      <h3 className="text-xs text-muted">{title}</h3>
      {movers.length === 0 ? (
        <p className="text-sm text-muted">{none}</p>
      ) : (
        <ul className="divide-y divide-rule rounded-control border border-rule">
          {movers.map((m) => {
            const call = calls.get(m.symbol)
            return (
              <li key={m.symbol} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="flex items-center gap-2">
                  <Link href={`/symbols/${m.symbol}`} className="font-mono font-medium hover:underline">
                    {m.symbol}
                  </Link>
                  {call && <ActionBadge action={call.action} />}
                </span>
                <span className={cn("text-right font-mono text-sm", m.change_pct >= 0 ? "text-ok" : "text-bad")}>
                  {formatPercent(m.change_pct)}
                  <span className="block text-xs">{formatSignedCurrency(m.change)}</span>
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
