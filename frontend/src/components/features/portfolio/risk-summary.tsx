"use client"

import Link from "next/link"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { drawdown } from "@/lib/charts"
import { formatDate, formatShare } from "@/lib/format"
import { useExposure, usePerformance } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"

/** Concentration, cash, market sensitivity, the fall from the high, and what moves together. */
export function RiskSummary() {
  const exposure = useExposure()
  const performance = usePerformance()

  if (exposure.isPending) return <Loading label="Loading risk" className="h-40" />
  if (exposure.isError) return <LoadError what="the risk readings" error={exposure.error} />
  const r = exposure.data.risk
  const fall = performance.data ? drawdown(performance.data.series) : null

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <Reading
          label="Largest position"
          value={r.largest_symbol && r.largest_weight !== null ? formatShare(r.largest_weight) : "—"}
          note={r.largest_symbol ?? "Nothing held"}
          warn={(r.largest_weight ?? 0) >= 25}
        />
        <Reading
          label="Cash"
          value={r.cash_weight === null ? "—" : formatShare(r.cash_weight)}
          note="Of the portfolio"
        />
        <Reading
          label="Beta of the holdings"
          value={r.beta === null ? "—" : r.beta.toFixed(2)}
          note={
            r.beta === null
              ? "No beta from the risk agent yet"
              : `Covers ${formatShare(r.beta_coverage ?? 0)} of the holdings · 1.00 = the market`
          }
          warn={(r.beta ?? 0) >= 1.3}
        />
        <Reading
          label="Below the high"
          value={fall === null ? "—" : fall.current === 0 ? "0.0%" : `${fall.current.toFixed(1)}%`}
          note={
            fall === null
              ? "After the second session"
              : `${fall.peak ? `From ${formatDate(fall.peak)} · ` : "At a high · "}worst ${fall.worst.toFixed(1)}%`
          }
          warn={(fall?.current ?? 0) <= -10}
        />
      </dl>
      <section aria-label="Moving together" className="space-y-1.5">
        <h3 className="text-xs text-muted">Moving together</h3>
        {r.together.length === 0 ? (
          <p className="text-sm text-muted">
            No two holdings move closely together (daily returns, last 60 sessions).
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {r.together.map((p) => (
              <li key={`${p.first}-${p.second}`} className="flex items-baseline justify-between gap-3">
                <span className="font-mono">
                  <Link href={`/symbols/${p.first}`} className="hover:underline">
                    {p.first}
                  </Link>
                  {" & "}
                  <Link href={`/symbols/${p.second}`} className="hover:underline">
                    {p.second}
                  </Link>
                </span>
                <span className="text-xs text-muted">
                  <span className="font-mono text-ink-2">{p.correlation.toFixed(2)}</span> over{" "}
                  <span className="font-mono">{p.sessions}</span> sessions
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function Reading({ label, value, note, warn }: { label: string; value: string; note: string; warn?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={cn("font-mono text-lg tabular-nums", warn ? "text-bad" : "text-ink")}>{value}</dd>
      <dd className="text-xs text-muted">{note}</dd>
    </div>
  )
}
