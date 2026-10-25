"use client"

import Link from "next/link"

import { ActionBadge } from "@/components/features/stocks/action-badge"
import { Badge } from "@/components/ui/badge"
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
import { useSymbols } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import type { Compliance } from "@/types/api"

/** Short marker for a row whose reasoning was flagged or replaced by the compliance review. */
function ComplianceMarker({ compliance }: { compliance: Compliance }) {
  if (compliance.status === "pass") return null
  return (
    <Badge
      variant={compliance.status === "fail" ? "loss" : "outline"}
      aria-label={
        compliance.status === "fail" ? "Compliance: original reasoning replaced" : "Compliance: flagged"
      }
    >
      {compliance.status === "fail" ? "Replaced" : "Flagged"}
    </Badge>
  )
}

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
        <span className="text-red-400">Could not load the watchlist: {error.message}</span>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          Retry
        </Button>
      </div>
    )
  }

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
            <TableHead className="text-right">Confidence</TableHead>
            <TableHead>As of</TableHead>
            <TableHead className="hidden md:table-cell">Summary</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map(({ symbol, recommendation: rec }) => (
            <TableRow key={symbol}>
              <TableCell className="font-mono font-semibold">
                <Link href={`/symbols/${symbol}`} className="hover:underline">
                  {symbol}
                </Link>
              </TableCell>
              {rec ? (
                <>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <ActionBadge action={rec.action} />
                      <ComplianceMarker compliance={rec.compliance} />
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    <span className={cn("rounded px-1.5 py-0.5", toneClasses(rec.weighted_score))}>
                      {formatScore(rec.weighted_score)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono">{formatConfidence(rec.confidence)}</TableCell>
                  <TableCell className="text-zinc-400">{formatDate(rec.run_date)}</TableCell>
                  <TableCell className="hidden max-w-md truncate text-zinc-400 md:table-cell">
                    {rec.reasoning}
                  </TableCell>
                </>
              ) : (
                <TableCell colSpan={5} className="text-zinc-400">
                  Not analysed yet
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {disclaimer && (
        <p className="border-t border-zinc-800 px-4 py-3 text-xs text-zinc-400">{disclaimer}</p>
      )}
    </>
  )
}
