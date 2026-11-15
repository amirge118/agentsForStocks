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
 * The biggest gainers and losers among the holdings this week, side by side, with the
 * agents' call. Before the portfolio has a session of its own, the last session's moves
 * stand in. Each bar is the move against the largest one shown.
 */
export function WeeklyMovers() {
  const performance = usePerformance()
  const portfolio = usePortfolio()
  const symbols = useSymbols()

  if (performance.isPending || portfolio.isPending) return <Loading label="Loading movers" className="h-36" />
  if (performance.isError) return <LoadError what="the movers" error={performance.error} />
  if (portfolio.isError) return <LoadError what="the movers" error={portfolio.error} />
  if (portfolio.data.positions.length === 0) return null

  const weekly = performance.data.series.length > 0
  const movers = weekly
    ? [...performance.data.gainers, ...performance.data.losers]
    : sessionMovers(portfolio.data.positions)
  const gainers = movers
    .filter((m) => m.change_pct > 0)
    .sort((a, b) => b.change_pct - a.change_pct)
    .slice(0, SHOWN)
  const losers = movers
    .filter((m) => m.change_pct < 0)
    .sort((a, b) => a.change_pct - b.change_pct)
    .slice(0, SHOWN)
  const largest = Math.max(...[...gainers, ...losers].map((m) => Math.abs(m.change_pct)), 0)
  const asOf = portfolio.data.positions.find((p) => p.price_as_of)?.price_as_of
  const calls = new Map(symbols.data?.map((s) => [s.symbol, s.recommendation]) ?? [])
  const period = weekly
    ? performance.data.week_start
      ? `This week · since the close of ${formatDate(performance.data.week_start)}`
      : "This week · since each came in"
    : `Last session${asOf ? ` · ${formatDate(asOf)}` : ""}`

  return (
    <section aria-label="Movers" className="rounded-card border border-rule bg-paper-2">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 pt-3 pb-2">
        <h2 className="text-base font-medium">Movers</h2>
        <p className="text-xs text-muted">{period}</p>
      </header>
      <div className="grid grid-cols-1 border-t border-rule md:grid-cols-2 md:divide-x md:divide-rule">
        <MoverList title="Gainers" movers={gainers} largest={largest} calls={calls} />
        <MoverList title="Losers" movers={losers} largest={largest} calls={calls} />
      </div>
    </section>
  )
}

function MoverList({
  title,
  movers,
  largest,
  calls,
}: {
  title: string
  movers: Mover[]
  largest: number
  calls: Map<string, Recommendation | null>
}) {
  return (
    <section aria-label={title} className="px-4 py-2">
      <h3 className="py-1 text-xs text-muted">{title}</h3>
      {movers.length === 0 ? (
        <p className="py-1.5 text-sm text-muted">None.</p>
      ) : (
        <ul>
          {movers.map((m) => {
            const call = calls.get(m.symbol)
            const up = m.change_pct >= 0
            return (
              <li key={m.symbol} className="grid grid-cols-[3.5rem_3.5rem_minmax(0,1fr)_4.5rem_5rem] items-center gap-2 py-1.5 text-sm">
                <Link href={`/symbols/${m.symbol}`} className="font-mono font-medium hover:underline">
                  {m.symbol}
                </Link>
                <span>{call && <ActionBadge action={call.action} />}</span>
                <span aria-hidden className="h-1.5 overflow-hidden rounded-chip bg-paper-3">
                  <span
                    className={cn("block h-full rounded-chip", up ? "bg-ok" : "bg-bad")}
                    style={{ width: `${largest > 0 ? (Math.abs(m.change_pct) / largest) * 100 : 0}%` }}
                  />
                </span>
                <span className={cn("text-right font-mono tabular-nums", up ? "text-ok" : "text-bad")}>
                  {formatPercent(m.change_pct)}
                </span>
                <span className="text-right font-mono text-xs tabular-nums text-muted">
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
