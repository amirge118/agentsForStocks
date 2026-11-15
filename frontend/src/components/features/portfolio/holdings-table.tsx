"use client"

import Link from "next/link"

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

/**
 * What is held, at today's prices, next to what the agents say about each symbol.
 * A holding without a price shows dashes, never a value of 0.
 */
export function HoldingsTable() {
  const portfolio = usePortfolio()
  const symbols = useSymbols()

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
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead className="text-right">Value</TableHead>
          <TableHead className="hidden text-right sm:table-cell">Weight</TableHead>
          <TableHead className="text-right">Today</TableHead>
          <TableHead className="hidden text-right md:table-cell">Price</TableHead>
          <TableHead className="hidden text-right lg:table-cell">Shares</TableHead>
          <TableHead className="text-right">P/L</TableHead>
          <TableHead className="hidden sm:table-cell">Agents</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((p) => (
          <HoldingRow key={p.symbol} position={p} call={calls.get(p.symbol) ?? null} />
        ))}
        <TableRow>
          <TableCell className="text-ink-2">Cash</TableCell>
          <TableCell className="text-right font-mono">{formatCurrency(cash)}</TableCell>
          <TableCell className="hidden text-right font-mono sm:table-cell">
            {total_value > 0 ? formatShare((cash / total_value) * 100) : "—"}
          </TableCell>
          <TableCell colSpan={5} className="hidden sm:table-cell" />
        </TableRow>
      </TableBody>
    </Table>
  )
}

function HoldingRow({ position: p, call }: { position: Position; call: Recommendation | null }) {
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
      <TableCell className="text-right font-mono">{p.value === null ? "—" : formatCurrency(p.value)}</TableCell>
      <TableCell className="hidden text-right font-mono sm:table-cell">
        {p.weight === null ? "—" : formatShare(p.weight)}
      </TableCell>
      <TableCell className={cn("text-right font-mono", tone(p.day_change))}>
        {p.day_change === null ? "—" : formatSignedCurrency(p.day_change)}
      </TableCell>
      <TableCell className="hidden text-right md:table-cell">
        <span className="font-mono">{p.price === null ? "—" : formatCurrency(p.price)}</span>
        {p.price_as_of && (
          <span className={cn("block text-xs", p.price_stale ? "text-bad" : "text-muted")}>
            {p.price_stale ? `Last close ${formatDate(p.price_as_of)}` : formatDate(p.price_as_of)}
          </span>
        )}
      </TableCell>
      <TableCell className="hidden text-right lg:table-cell">
        <span className="font-mono">{p.shares.toLocaleString("en-US", { maximumFractionDigits: 6 })}</span>
        <span className="block text-xs text-muted">
          at <span className="font-mono">{formatCurrency(p.avg_cost)}</span>
        </span>
      </TableCell>
      <TableCell className={cn("text-right", tone(p.unrealised_pnl))}>
        <span className="font-mono">{p.unrealised_pnl === null ? "—" : formatSignedCurrency(p.unrealised_pnl)}</span>
        {p.unrealised_pct !== null && (
          <span className="block font-mono text-xs">{formatPercent(p.unrealised_pct)}</span>
        )}
      </TableCell>
      <TableCell className="hidden sm:table-cell">
        {call ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <ActionBadge action={call.action} />
            <span className="font-mono text-xs text-ink-2">{formatScore(call.weighted_score)}</span>
            <span className="text-xs text-muted">
              <span className="font-mono">{formatConfidence(call.confidence)}</span> sure ·{" "}
              {formatDate(call.run_date)}
            </span>
          </div>
        ) : (
          <span className="text-xs text-muted">Not analysed yet</span>
        )}
      </TableCell>
    </TableRow>
  )
}
