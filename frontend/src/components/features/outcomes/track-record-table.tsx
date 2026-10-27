"use client"

import { useState } from "react"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { HorizonPicker } from "@/components/features/outcomes/horizon-picker"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatHitRate, formatReturn } from "@/lib/format"
import { useTrackRecord } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import type { AgentTrackRecord, Horizon, TrackGroup } from "@/types/api"

const SIGNALS = ["bullish", "neutral", "bearish"] as const
const BUCKETS = ["0-40", "40-60", "60-80", "80-100"] as const

/** Every agent's settled calls: how often each was right and what following it earned. */
export function TrackRecordTable() {
  const [horizon, setHorizon] = useState<Horizon>(20)
  const { data, isPending, isError, error } = useTrackRecord(horizon)

  return (
    <div className="space-y-4">
      <div className="px-6">
        <HorizonPicker value={horizon} onChange={setHorizon} />
      </div>
      {isPending ? (
        <Loading label="Loading track record" />
      ) : isError ? (
        <LoadError what="the track record" error={error} />
      ) : data.agents.length === 0 ? (
        <Empty>
          No settled calls yet. {data.pending} outcomes are pending: a call is judged once its
          window has fully traded.
        </Empty>
      ) : (
        <>
          <dl className="grid grid-cols-3 gap-4 px-6" aria-label="Outcomes">
            <Stat label="Settled" value={data.settled} />
            <Stat label="Pending" value={data.pending} />
            <Stat label="No prices" value={data.unavailable} />
          </dl>
          <Table aria-label="Track record">
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead className="text-right">Calls</TableHead>
                <TableHead className="text-right">Right</TableHead>
                <TableHead className="text-right">Alpha captured</TableHead>
                {SIGNALS.map((s) => (
                  <TableHead key={s} className="hidden text-right capitalize md:table-cell">
                    {s}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="tabular-nums">
              {data.agents.map((a) => (
                <TableRow key={a.agent}>
                  <TableCell className="font-mono">{a.agent.replaceAll("_", " ")}</TableCell>
                  <TableCell className="text-right">{a.overall.calls}</TableCell>
                  <TableCell className="text-right">{formatHitRate(a.overall.hit_rate)}</TableCell>
                  <AlphaCell value={a.overall.mean_alpha_captured} />
                  {SIGNALS.map((s) => (
                    <TableCell key={s} className="hidden text-right md:table-cell">
                      <GroupCell group={a.by_signal.find((g) => g.key === s)} />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Calibration agents={data.agents} />
        </>
      )}
    </div>
  )
}

/** Right-rate per confidence bucket: a calibrated agent is right more often when surer. */
function Calibration({ agents }: { agents: AgentTrackRecord[] }) {
  return (
    <Table aria-label="Calibration">
      <TableHeader>
        <TableRow>
          <TableHead>Right, by confidence</TableHead>
          {BUCKETS.map((b) => (
            <TableHead key={b} className="text-right whitespace-nowrap">
              {b}%
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody className="tabular-nums">
        {agents.map((a) => (
          <TableRow key={a.agent}>
            <TableCell className="font-mono">{a.agent.replaceAll("_", " ")}</TableCell>
            {BUCKETS.map((b) => (
              <TableCell key={b} className="text-right">
                <GroupCell group={a.by_confidence.find((g) => g.key === b)} />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function GroupCell({ group }: { group: TrackGroup | undefined }) {
  if (!group) return <span className="text-muted">none</span>
  return (
    <span className="whitespace-nowrap">
      {formatHitRate(group.hit_rate)}
      <span className="hidden text-muted sm:inline"> of {group.calls}</span>
    </span>
  )
}

export function AlphaCell({ value, className }: { value: number | null; className?: string }) {
  return (
    <TableCell
      className={cn(
        "text-right font-mono",
        value === null || value === 0 ? "text-muted" : value > 0 ? "text-ok" : "text-bad",
        className,
      )}
    >
      {formatReturn(value)}
    </TableCell>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-mono text-lg tabular-nums">{value}</dd>
    </div>
  )
}
