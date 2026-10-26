"use client"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { RunFilters } from "@/lib/api/repositories"
import { formatCost, formatDateTime, formatTokens } from "@/lib/format"
import { useRuns } from "@/lib/hooks/queries"
import type { RunStatus } from "@/types/api"

const STATUS_VARIANT: Record<RunStatus, "gain" | "loss" | "outline"> = {
  completed: "gain",
  failed: "loss",
  skipped: "outline",
}

export function AgentRunsTable({ filters = {} }: { filters?: RunFilters }) {
  const { data, isPending, isError, error } = useRuns(filters)

  if (isPending) {
    return <Loading label="Loading runs" />
  }
  if (isError) {
    return <LoadError what="runs" error={error} />
  }
  if (data.length === 0) {
    return <Empty>No agent runs yet.</Empty>
  }

  return (
    <Table aria-label="Agent runs">
      <TableHeader>
        <TableRow>
          <TableHead>Started</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Agent</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="hidden text-right md:table-cell">Tokens</TableHead>
          <TableHead className="hidden text-right md:table-cell">Cost</TableHead>
          <TableHead className="hidden md:table-cell">Error</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((run) => (
          <TableRow key={run.run_id}>
            <TableCell className="text-muted">{formatDateTime(run.started_at)}</TableCell>
            <TableCell className="font-mono">{run.symbol}</TableCell>
            <TableCell>{run.agent_type.replaceAll("_", " ")}</TableCell>
            <TableCell>
              <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
              {run.llm_fallbacks > 0 && (
                <Badge variant="outline" className="ml-2" title="Claude was unavailable — the agent used its own quantitative signal">
                  fallback
                </Badge>
              )}
            </TableCell>
            <TableCell className="hidden text-right font-mono tabular-nums md:table-cell">
              {run.llm_calls > 0 ? (
                <Link href={`/runs/${encodeURIComponent(run.run_id)}`} className="hover:text-ink hover:underline">
                  {formatTokens(run.input_tokens)} / {formatTokens(run.output_tokens)}
                </Link>
              ) : (
                <span className="text-muted">None</span>
              )}
            </TableCell>
            <TableCell className="hidden text-right font-mono tabular-nums md:table-cell">
              {run.llm_calls > 0 ? formatCost(run.cost_usd) : ""}
            </TableCell>
            <TableCell className="hidden max-w-md truncate text-bad md:table-cell">
              {run.error}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
