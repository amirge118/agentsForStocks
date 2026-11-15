"use client"

import Link from "next/link"
import { useState } from "react"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { ActionBadge } from "@/components/features/stocks/action-badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  formatConfidence,
  formatCurrency,
  formatDate,
  formatPercent,
  formatScore,
  formatShare,
  formatSignedCurrency,
} from "@/lib/format"
import { usePortfolio, useSymbols } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import type { Position, Recommendation } from "@/types/api"

const tone = (n: number | null) => (n === null ? "text-muted" : n > 0 ? "text-ok" : n < 0 ? "text-bad" : "text-ink-2")

export type SortKey = "symbol" | "value" | "weight" | "today" | "price" | "shares" | "pnl" | "agents"
export interface Sort {
  key: SortKey
  desc: boolean
}

export interface Row {
  position: Position
  call: Recommendation | null
  todayPct: number | null
}

/** Today's move in percent: the day's change against the value before it. */
export function todayPct(p: Position): number | null {
  if (p.value === null || p.day_change === null) return null
  const before = p.value - p.day_change
  return before > 0 ? (p.day_change / before) * 100 : null
}

const SORT_VALUE: Record<SortKey, (r: Row) => number | string | null> = {
  symbol: (r) => r.position.symbol,
  value: (r) => r.position.value,
  weight: (r) => r.position.weight,
  today: (r) => r.todayPct,
  price: (r) => r.position.price,
  shares: (r) => r.position.shares,
  pnl: (r) => r.position.unrealised_pct,
  agents: (r) => r.call?.weighted_score ?? null,
}

/** Sorted by one column; a holding without that figure always goes last. */
export function sortRows(rows: Row[], sort: Sort): Row[] {
  const read = SORT_VALUE[sort.key]
  return [...rows].sort((a, b) => {
    const x = read(a)
    const y = read(b)
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1
    const order = typeof x === "string" ? x.localeCompare(String(y)) : x - Number(y)
    return sort.desc ? -order : order
  })
}

const COLUMNS: { key: SortKey; label: string; className: string; title?: string }[] = [
  { key: "symbol", label: "Symbol", className: "" },
  { key: "value", label: "Value", className: "text-right" },
  { key: "weight", label: "Weight", className: "hidden text-right sm:table-cell" },
  { key: "today", label: "Today", className: "text-right" },
  { key: "price", label: "Price", className: "hidden text-right md:table-cell" },
  { key: "shares", label: "Shares", className: "hidden text-right lg:table-cell" },
  { key: "pnl", label: "P/L", className: "text-right", title: "Against what the shares cost, fees included" },
  { key: "agents", label: "Agents", className: "hidden sm:table-cell", title: "The agents' latest call and score" },
]

/**
 * What is held, at today's prices, next to what the agents say about each symbol; every
 * column sorts. A holding without a price shows dashes, never a value of 0. Cash stays last.
 */
export function HoldingsTable() {
  const portfolio = usePortfolio()
  const symbols = useSymbols()
  const [sort, setSort] = useState<Sort>({ key: "value", desc: true })

  if (portfolio.isPending) return <Loading label="Loading holdings" />
  if (portfolio.isError) return <LoadError what="the holdings" error={portfolio.error} />

  const { positions, cash, total_value } = portfolio.data
  if (positions.length === 0) {
    return (
      <Empty>
        No holdings yet. Record a deposit and then a buy, or bring in a position you already hold
        (&ldquo;Transfer in&rdquo; at what it cost you).
      </Empty>
    )
  }
  const calls = new Map(symbols.data?.map((s) => [s.symbol, s.recommendation]) ?? [])
  const rows = sortRows(
    positions.map((p) => ({ position: p, call: calls.get(p.symbol) ?? null, todayPct: todayPct(p) })),
    sort,
  )
  const toggle = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== "symbol" }))

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {COLUMNS.map((c) => {
            const active = sort.key === c.key
            return (
              <TableHead
                key={c.key}
                className={c.className}
                aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
              >
                <button
                  type="button"
                  onClick={() => toggle(c.key)}
                  title={c.title}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-chip hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                    active && "text-ink",
                  )}
                >
                  {c.label}
                  <span aria-hidden className={cn("w-2 text-[10px]", !active && "invisible")}>
                    {sort.desc ? "▼" : "▲"}
                  </span>
                </button>
              </TableHead>
            )
          })}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <HoldingRow key={r.position.symbol} row={r} />
        ))}
        <TableRow className="hover:bg-transparent">
          <TableCell className="text-ink-2">Cash</TableCell>
          <TableCell className="text-right font-mono tabular-nums">{formatCurrency(cash)}</TableCell>
          <TableCell className="hidden text-right font-mono tabular-nums text-ink-2 sm:table-cell">
            {total_value > 0 ? formatShare((cash / total_value) * 100) : "—"}
          </TableCell>
          <TableCell colSpan={5} className="hidden sm:table-cell" />
        </TableRow>
      </TableBody>
    </Table>
  )
}

function HoldingRow({ row: { position: p, call, todayPct: pct } }: { row: Row }) {
  return (
    <TableRow>
      <TableCell className="font-mono font-medium">
        <Link href={`/symbols/${p.symbol}`} className="hover:underline">
          {p.symbol}
        </Link>
        {/* On a phone the Agents column is hidden: the call sits under the symbol */}
        {call && (
          <span className="mt-1 block sm:hidden">
            <ActionBadge action={call.action} />
          </span>
        )}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">
        {p.value === null ? "—" : formatCurrency(p.value)}
      </TableCell>
      <TableCell className="hidden text-right font-mono tabular-nums text-ink-2 sm:table-cell">
        {p.weight === null ? "—" : formatShare(p.weight)}
      </TableCell>
      <TableCell className={cn("text-right font-mono tabular-nums", tone(p.day_change))}>
        {pct === null ? "—" : formatPercent(pct)}
        {p.day_change !== null && <span className="block text-xs">{formatSignedCurrency(p.day_change)}</span>}
      </TableCell>
      <TableCell className="hidden text-right md:table-cell">
        <span className="font-mono tabular-nums">{p.price === null ? "—" : formatCurrency(p.price)}</span>
        {p.price_stale && p.price_as_of && (
          <span className="block text-xs text-bad">Last close {formatDate(p.price_as_of)}</span>
        )}
      </TableCell>
      <TableCell className="hidden text-right lg:table-cell">
        <span className="font-mono tabular-nums">
          {p.shares.toLocaleString("en-US", { maximumFractionDigits: 6 })}
        </span>
        <span className="block text-xs text-muted">
          avg <span className="font-mono">{formatCurrency(p.avg_cost)}</span>
        </span>
      </TableCell>
      <TableCell className={cn("text-right font-mono tabular-nums", tone(p.unrealised_pnl))}>
        {p.unrealised_pct === null ? "—" : formatPercent(p.unrealised_pct)}
        {p.unrealised_pnl !== null && (
          <span className="block text-xs">{formatSignedCurrency(p.unrealised_pnl)}</span>
        )}
      </TableCell>
      <TableCell className="hidden sm:table-cell">
        {call ? (
          <div
            className="flex items-center gap-2"
            title={`${formatConfidence(call.confidence)} sure · ${formatDate(call.run_date)}`}
          >
            <ActionBadge action={call.action} />
            <span className="font-mono text-xs text-ink-2">{formatScore(call.weighted_score)}</span>
            <span className="hidden font-mono text-xs text-muted xl:inline">{formatConfidence(call.confidence)}</span>
          </div>
        ) : (
          <span className="text-xs text-muted">Not analysed yet</span>
        )}
      </TableCell>
    </TableRow>
  )
}
