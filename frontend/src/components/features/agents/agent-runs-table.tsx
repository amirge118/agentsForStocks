"use client"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { RunFilters } from "@/lib/api/repositories"
import { formatDateTime } from "@/lib/format"
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
    return <Skeleton className="h-48 w-full" aria-label="Loading runs" />
  }
  if (isError) {
    return (
      <p role="alert" className="p-6 text-sm text-red-400">
        Could not load runs: {error.message}
      </p>
    )
  }
  if (data.length === 0) {
    return <p className="p-6 text-sm text-zinc-400">No agent runs yet.</p>
  }

  return (
    <Table aria-label="Agent runs">
      <TableHeader>
        <TableRow>
          <TableHead>Started</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Agent</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="hidden md:table-cell">Error</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((run) => (
          <TableRow key={run.run_id}>
            <TableCell className="text-zinc-400">{formatDateTime(run.started_at)}</TableCell>
            <TableCell className="font-mono">{run.symbol}</TableCell>
            <TableCell>{run.agent_type.replaceAll("_", " ")}</TableCell>
            <TableCell>
              <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
            </TableCell>
            <TableCell className="hidden max-w-md truncate text-red-400 md:table-cell">
              {run.error}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
