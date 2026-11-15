"use client"

import Link from "next/link"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { ActionBadge } from "@/components/features/stocks/action-badge"
import { formatDate, formatPercent, formatSignedCurrency } from "@/lib/format"
import { usePerformance, usePortfolio, useSymbols } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import type { Mover, Position, Recommendation } from "@/types/api"

const SHOWN = 3

/** Each holding's move over the last session, from its value and the day's change. */
export function sessionMovers(positions: Position[]): Mover[] {
  return positions.flatMap((p) => {
    if (p.value === null || p.day_change === null || p.day_change === 0) return []
    const before = p.value - p.day_change
    return before > 0 ? [{ symbol: p.symbol, change: p.day_change, change_pct: (p.day_change / before) * 100 }] : []
  })
}

/**
 * The biggest gainers and losers among the holdings this week, with the agents' call. Before
 * the portfolio has a session of its own, the last session's moves stand in.
 */
export function WeeklyMovers() {
  const performance = usePerformance()
  const portfolio = usePortfolio()
  const symbols = useSymbols()

  if (performance.isPending || portfolio.isPending) return <Loading label="Loading movers" className="h-32" />
  if (performance.isError) return <LoadError what="the movers" error={performance.error} />
  if (portfolio.isError) return <LoadError what="the movers" error={portfolio.error} />

  const weekly = performance.data.series.length > 0
  const movers = weekly
    ? [...performance.data.gainers, ...performance.data.losers]
    : sessionMovers(portfolio.data.positions)
  const gainers = movers.filter((m) => m.change_pct > 0).sort((a, b) => b.change_pct - a.change_pct)
  const losers = movers.filter((m) => m.change_pct < 0).sort((a, b) => a.change_pct - b.change_pct)
  const asOf = portfolio.data.positions.find((p) => p.price_as_of)?.price_as_of
  const calls = new Map(symbols.data?.map((s) => [s.symbol, s.recommendation]) ?? [])
  const since = weekly
    ? performance.data.week_start
      ? `This week, since the close of ${formatDate(performance.data.week_start)}`
      : "This week, since each came in"
    : `Last session${asOf ? ` (${formatDate(asOf)})` : ""}: the week starts after your first session`

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">{since}</p>
      {gainers.length + losers.length === 0 ? (
        <p className="text-sm text-muted">No moves yet.</p>
      ) : (
        <div className="space-y-3">
          <MoverList title="Gainers" movers={gainers.slice(0, SHOWN)} calls={calls} />
          <MoverList title="Losers" movers={losers.slice(0, SHOWN)} calls={calls} />
        </div>
      )}
    </div>
  )
}

function MoverList({
  title,
  movers,
  calls,
}: {
  title: string
  movers: Mover[]
  calls: Map<string, Recommendation | null>
}) {
  return (
    <section aria-label={title}>
      <h3 className="mb-1 text-xs text-muted">{title}</h3>
      {movers.length === 0 ? (
        <p className="text-sm text-muted">None.</p>
      ) : (
        <ul className="divide-y divide-rule">
          {movers.map((m) => {
            const call = calls.get(m.symbol)
            return (
              <li key={m.symbol} className="flex items-center gap-2 py-1.5 text-sm">
                <Link href={`/symbols/${m.symbol}`} className="w-14 font-mono font-medium hover:underline">
                  {m.symbol}
                </Link>
                <span className="w-12">{call && <ActionBadge action={call.action} />}</span>
                <span
                  className={cn(
                    "ml-auto text-right font-mono tabular-nums",
                    m.change_pct >= 0 ? "text-ok" : "text-bad",
                  )}
                >
                  {formatPercent(m.change_pct)}
                </span>
                <span className="w-20 text-right font-mono text-xs tabular-nums text-muted">
                  {formatSignedCurrency(m.change)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
