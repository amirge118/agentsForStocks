"use client"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatCost, formatTokens } from "@/lib/format"
import { useLLMUsage } from "@/lib/hooks/queries"
import type { UsageGroup } from "@/types/api"

const GROUPS: { value: UsageGroup; label: string }[] = [
  { value: "agent", label: "Agent" },
  { value: "model", label: "Model" },
  { value: "provider", label: "Provider" },
  { value: "day", label: "Day" },
  { value: "prompt_version", label: "Prompt version" },
]
const PERIODS = [1, 7, 30] as const

/** Token and cost totals from the LLM ledger, grouped by agent / model / provider / day / prompt. */
export function UsageTable() {
  const [groupBy, setGroupBy] = useState<UsageGroup>("agent")
  const [days, setDays] = useState<number>(7)
  const { data, isPending, isError, error } = useLLMUsage(days, groupBy)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 px-6" role="toolbar" aria-label="Usage filters">
        {GROUPS.map((g) => (
          <Button
            key={g.value}
            size="sm"
            variant={g.value === groupBy ? "default" : "outline"}
            aria-pressed={g.value === groupBy}
            onClick={() => setGroupBy(g.value)}
          >
            {g.label}
          </Button>
        ))}
        <span className="mx-2 h-5 w-px bg-zinc-800" aria-hidden />
        {PERIODS.map((d) => (
          <Button
            key={d}
            size="sm"
            variant={d === days ? "default" : "outline"}
            aria-pressed={d === days}
            onClick={() => setDays(d)}
          >
            {d === 1 ? "24h" : `${d}d`}
          </Button>
        ))}
      </div>
      {isPending ? (
        <Loading label="Loading usage" />
      ) : isError ? (
        <LoadError what="usage" error={error} />
      ) : data.rows.length === 0 ? (
        <Empty>No LLM calls in this period.</Empty>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-4 px-6 md:grid-cols-4" aria-label="Totals">
            <Stat label="Calls" value={formatTokens(data.total_calls)} />
            <Stat label="Input tokens" value={formatTokens(data.total_input_tokens)} />
            <Stat label="Output tokens" value={formatTokens(data.total_output_tokens)} />
            <Stat label="Cost" value={formatCost(data.total_cost_usd)} />
          </dl>
          <Table aria-label="LLM usage">
            <TableHeader>
              <TableRow>
                <TableHead>{GROUPS.find((g) => g.value === groupBy)?.label}</TableHead>
                <TableHead className="text-right">Calls</TableHead>
                <TableHead className="text-right">Errors</TableHead>
                <TableHead className="text-right">Input</TableHead>
                <TableHead className="text-right">Output</TableHead>
                <TableHead className="hidden text-right md:table-cell">Cache read</TableHead>
                <TableHead className="text-right">Cost</TableHead>
                <TableHead className="hidden text-right md:table-cell">Avg latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="tabular-nums">
              {data.rows.map((row) => (
                <TableRow key={row.key}>
                  <TableCell className="font-mono">{row.key.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-right">{row.calls}</TableCell>
                  <TableCell className={row.errors ? "text-right text-red-400" : "text-right"}>
                    {row.errors}
                  </TableCell>
                  <TableCell className="text-right font-mono">{formatTokens(row.input_tokens)}</TableCell>
                  <TableCell className="text-right font-mono">{formatTokens(row.output_tokens)}</TableCell>
                  <TableCell className="hidden text-right font-mono md:table-cell">
                    {formatTokens(row.cache_read_tokens)}
                  </TableCell>
                  <TableCell className="text-right font-mono">{formatCost(row.cost_usd)}</TableCell>
                  <TableCell className="hidden text-right md:table-cell">
                    {Math.round(row.avg_latency_ms)} ms
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <dt className="text-xs text-zinc-400">{label}</dt>
      <dd className="font-mono text-lg tabular-nums">{value}</dd>
    </div>
  )
}
