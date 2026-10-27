"use client"

import Link from "next/link"
import { useState } from "react"

import { ActionBadge } from "@/components/features/stocks/action-badge"
import { ComplianceMarker } from "@/components/features/stocks/compliance-marker"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatConfidence, formatDate, formatScore, toneClasses } from "@/lib/format"
import { useSymbols, useWatchlistMutations } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"

import { ScoreSparkline } from "./score-sparkline"

export function WatchlistTable() {
  const { data, isPending, isError, error, refetch } = useSymbols()

  if (isPending) {
    return (
      <div className="space-y-2 p-4" aria-label="Loading watchlist">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div role="alert" className="flex items-center justify-between p-6 text-sm">
        <span className="text-bad">Could not load the watchlist: {error.message}</span>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          Retry
        </Button>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <p role="status" className="p-6 text-sm text-muted">
        The watchlist is empty. Add a ticker above: it is analysed in the next daily run (weekdays, 18:30 New York
        time), or right away with Run analysis.
      </p>
    )
  }

  const symbols = data.map((row) => row.symbol)
  // Every recommendation carries the same backend disclaimer; show it once under the table
  const disclaimer = data.find((row) => row.recommendation)?.recommendation?.disclaimer

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead>Recommendation</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead className="hidden text-right sm:table-cell">Confidence</TableHead>
            <TableHead className="hidden sm:table-cell">As of</TableHead>
            <TableHead className="hidden lg:table-cell">Trend</TableHead>
            <TableHead className="hidden md:table-cell">Summary</TableHead>
            <TableHead className="text-right">
              <span className="sr-only">Order and remove</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map(({ symbol, recommendation: rec }, index) => (
            <TableRow key={symbol}>
              <TableCell className="font-mono font-medium">
                <Link href={`/symbols/${symbol}`} className="hover:underline">
                  {symbol}
                </Link>
              </TableCell>
              {rec ? (
                <>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <ActionBadge action={rec.action} />
                      <ComplianceMarker status={rec.compliance.status} findings={rec.compliance.findings} />
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    <span className={cn("rounded-chip px-1.5 py-0.5", toneClasses(rec.weighted_score))}>
                      {formatScore(rec.weighted_score)}
                    </span>
                  </TableCell>
                  <TableCell className="hidden text-right font-mono sm:table-cell">
                    {formatConfidence(rec.confidence)}
                  </TableCell>
                  <TableCell className="hidden text-muted sm:table-cell">{formatDate(rec.run_date)}</TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <ScoreSparkline symbol={symbol} />
                  </TableCell>
                  <TableCell className="hidden max-w-md truncate text-muted md:table-cell">
                    {rec.reasoning}
                  </TableCell>
                </>
              ) : (
                <>
                  {/* One cell per hidden column too, so the controls stay in their column at every width */}
                  <TableCell colSpan={2} className="text-muted">
                    Not analysed yet
                  </TableCell>
                  <TableCell className="hidden sm:table-cell" />
                  <TableCell className="hidden sm:table-cell" />
                  <TableCell className="hidden lg:table-cell" />
                  <TableCell className="hidden md:table-cell" />
                </>
              )}
              <TableCell className="text-right">
                <RowControls symbol={symbol} index={index} symbols={symbols} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {disclaimer && (
        <p className="border-t border-rule px-4 py-3 text-xs text-muted">{disclaimer}</p>
      )}
    </>
  )
}

/** Move a symbol up or down, or remove it (the second click confirms; its history stays). */
function RowControls({ symbol, index, symbols }: { symbol: string; index: number; symbols: string[] }) {
  const { remove, reorder } = useWatchlistMutations()
  const [confirming, setConfirming] = useState(false)
  const move = (delta: -1 | 1) => {
    const next = [...symbols]
    const [item] = next.splice(index, 1)
    next.splice(index + delta, 0, item!)
    reorder.mutate(next)
  }
  const busy = remove.isPending || reorder.isPending
  return (
    <div className="flex items-center justify-end gap-1">
      <Button
        variant="ghost"
        size="sm"
        aria-label={`Move ${symbol} up`}
        disabled={busy || index === 0}
        onClick={() => move(-1)}
      >
        ↑
      </Button>
      <Button
        variant="ghost"
        size="sm"
        aria-label={`Move ${symbol} down`}
        disabled={busy || index === symbols.length - 1}
        onClick={() => move(1)}
      >
        ↓
      </Button>
      {confirming ? (
        <>
          <Button variant="destructive" size="sm" disabled={busy} onClick={() => remove.mutate(symbol)}>
            Remove {symbol}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
            Keep
          </Button>
        </>
      ) : (
        <Button variant="ghost" size="sm" aria-label={`Remove ${symbol}`} disabled={busy} onClick={() => setConfirming(true)}>
          Remove
        </Button>
      )}
    </div>
  )
}
