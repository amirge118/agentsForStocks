"use client"

import { useState } from "react"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { HorizonPicker } from "@/components/features/outcomes/horizon-picker"
import { AlphaCell } from "@/components/features/outcomes/track-record-table"
import { SignalText } from "@/components/features/stocks/signal-text"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatConfidence, formatDate, formatHitRate, formatReturn } from "@/lib/format"
import { useSymbolOutcomes } from "@/lib/hooks/queries"
import type { Horizon } from "@/types/api"

const SHOWN = 10

/** How this symbol's past recommendations turned out against the benchmark. */
export function TrackRecordCard({ symbol }: { symbol: string }) {
  const [horizon, setHorizon] = useState<Horizon>(20)
  const { data, isPending, isError, error } = useSymbolOutcomes(symbol, horizon)

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
        <div className="space-y-1.5">
          <CardTitle>Track record</CardTitle>
          <CardDescription>
            Past recommendations for {symbol}, judged {horizon} trading days later against the
            benchmark.
          </CardDescription>
        </div>
        <HorizonPicker value={horizon} onChange={setHorizon} />
      </CardHeader>
      <CardContent className="px-0">
        {isPending ? (
          <Loading label="Loading track record" className="h-32" />
        ) : isError ? (
          <LoadError what="the track record" error={error} />
        ) : data.calls.length === 0 ? (
          <Empty>
            No settled recommendations yet ({data.pending} pending). Each one is judged once its
            window has fully traded.
          </Empty>
        ) : (
          <div className="space-y-4">
            <p className="px-6 text-sm">
              Right on <strong className="font-medium">{data.overall.hits}</strong> of{" "}
              {data.overall.calls} calls ({formatHitRate(data.overall.hit_rate)}); following them
              captured{" "}
              <strong className="font-mono font-medium">
                {formatReturn(data.overall.mean_alpha_captured)}
              </strong>{" "}
              alpha per call. {data.pending} still pending.
            </p>
            <Table aria-label="Past recommendations">
              <TableHeader>
                <TableRow>
                  <TableHead>Decided</TableHead>
                  <TableHead>Call</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Confidence</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Return</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Benchmark</TableHead>
                  <TableHead className="text-right">Alpha</TableHead>
                  <TableHead className="text-right">Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="tabular-nums">
                {data.calls.slice(0, SHOWN).map((c) => (
                  <TableRow key={c.decision_date}>
                    <TableCell className="whitespace-nowrap">{formatDate(c.decision_date)}</TableCell>
                    <TableCell>
                      <SignalText signal={c.signal} />
                    </TableCell>
                    <TableCell className="hidden text-right sm:table-cell">
                      {formatConfidence(c.confidence)}
                    </TableCell>
                    <TableCell className="hidden text-right font-mono sm:table-cell">
                      {formatReturn(c.raw_return)}
                    </TableCell>
                    <TableCell className="hidden text-right font-mono sm:table-cell">
                      {c.benchmark} {formatReturn(c.benchmark_return)}
                    </TableCell>
                    <AlphaCell value={c.alpha} />
                    <TableCell className={c.hit ? "text-right text-ok" : "text-right text-bad"}>
                      {c.hit ? "Right" : "Wrong"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
