"use client"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { formatCurrency, formatPercent, formatShare, formatSignedCurrency } from "@/lib/format"
import { usePortfolio } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"

/** The headline figures: what everything is worth, how it moved today, the P/L, the cash. */
export function PortfolioSummary() {
  const { data, isPending, isError, error } = usePortfolio()
  if (isPending) return <Loading label="Loading the portfolio" className="h-28" />
  if (isError) return <LoadError what="the portfolio" error={error} />

  const unrealisedPct = data.cost_basis > 0 ? (data.unrealised_pnl / data.cost_basis) * 100 : null
  const cashShare = data.total_value > 0 ? (data.cash / data.total_value) * 100 : null
  return (
    <section aria-label="Portfolio summary" className="space-y-2">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-rule bg-rule md:grid-cols-5">
        <Figure label="Total value" value={formatCurrency(data.total_value)} note="Holdings and cash" big />
        <Figure
          label="Today"
          value={formatSignedCurrency(data.day_change)}
          note={data.day_change_pct === null ? "—" : formatPercent(data.day_change_pct)}
          tone={data.day_change}
        />
        <Figure
          label="Unrealised P/L"
          value={formatSignedCurrency(data.unrealised_pnl)}
          note={unrealisedPct === null ? "On what the holdings cost" : `${formatPercent(unrealisedPct)} on cost`}
          tone={data.unrealised_pnl}
        />
        <Figure
          label="Realised P/L"
          value={formatSignedCurrency(data.realised_pnl)}
          note={`Dividends ${formatCurrency(data.dividends)}`}
          tone={data.realised_pnl}
        />
        <Figure
          wide
          label="Cash"
          value={formatCurrency(data.cash)}
          note={cashShare === null ? "—" : `${formatShare(cashShare)} of the portfolio`}
        />
      </dl>
      {data.unpriced.length > 0 && (
        <p className="text-xs text-muted">
          No price for {data.unpriced.join(", ")}: left out of the totals until one comes in.
        </p>
      )}
    </section>
  )
}

function Figure({
  label,
  value,
  note,
  tone,
  big,
  wide,
}: {
  label: string
  value: string
  note: string
  tone?: number
  big?: boolean
  wide?: boolean // the odd one out on a two-column phone grid spans both columns
}) {
  return (
    <div className={cn("bg-paper-2 p-4", wide && "col-span-2 md:col-span-1")}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd
        className={cn(
          "mt-1 font-mono tabular-nums",
          big ? "text-2xl text-ink" : "text-lg",
          tone !== undefined && (tone > 0 ? "text-ok" : tone < 0 ? "text-bad" : "text-ink"),
        )}
      >
        {value}
      </dd>
      <dd className="mt-0.5 text-xs text-muted">{note}</dd>
    </div>
  )
}
