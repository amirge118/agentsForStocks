"use client"

import { useState } from "react"
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { RETURN_RANGES, returnSeries, type ReturnRange } from "@/lib/charts"
import { formatDate, formatPercent } from "@/lib/format"
import { usePerformance } from "@/lib/hooks/queries"
import { useThemeColors } from "@/lib/hooks/use-theme-colors"
import { cn } from "@/lib/utils"

/**
 * The portfolio's time-weighted return against the benchmark, both from 0% at the range's
 * first session. Deposits and withdrawals don't move the line: only how the money did.
 */
export function PerformanceChart() {
  const colors = useThemeColors()
  const [range, setRange] = useState<ReturnRange>("All")
  const { data, isPending, isError, error } = usePerformance()

  if (isPending) return <Loading label="Loading performance" className="h-48" />
  if (isError) return <LoadError what="the performance" error={error} />
  const points = returnSeries(data.series, range)
  if (points.length < 2) {
    return (
      <p className="text-sm text-muted">
        Your return against {data.benchmark}, without the money you put in or took out. The line starts once the
        portfolio has two trading sessions{data.since ? ` (from ${formatDate(data.since)})` : ""}.
      </p>
    )
  }
  const first = points[0]!
  const last = points[points.length - 1]!
  const ahead = last.benchmark === null ? null : last.portfolio - last.benchmark
  const summary = `Portfolio ${formatPercent(last.portfolio)}${
    last.benchmark === null ? "" : `, ${data.benchmark} ${formatPercent(last.benchmark)}`
  }, ${formatDate(first.day)} to ${formatDate(last.day)}`

  return (
    <figure aria-label="Return against the market" className="space-y-3">
      <figcaption className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-0.5 text-sm">
          <p>
            <span className="text-muted">Portfolio </span>
            <span className={cn("font-mono", last.portfolio >= 0 ? "text-ok" : "text-bad")}>
              {formatPercent(last.portfolio)}
            </span>
            {last.benchmark !== null && (
              <>
                <span className="text-muted"> · {data.benchmark} (dashed) </span>
                <span className="font-mono text-ink-2">{formatPercent(last.benchmark)}</span>
              </>
            )}
          </p>
          <p className="text-xs text-muted">
            {formatDate(first.day)} to {formatDate(last.day)}
            {ahead !== null && (
              <>
                {" · "}
                <span className="font-mono">{Math.abs(ahead).toFixed(2)}</span> pts {ahead >= 0 ? "ahead of" : "behind"}{" "}
                {data.benchmark}
              </>
            )}
          </p>
        </div>
        <div role="group" aria-label="Return range" className="flex rounded-control border border-rule bg-paper-3 p-0.5">
          {RETURN_RANGES.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={r === range}
              onClick={() => setRange(r)}
              className={cn(
                "rounded-chip px-2.5 py-1 font-mono text-xs transition-colors duration-[var(--dur-micro)]",
                r === range ? "bg-paper-2 text-ink" : "text-muted hover:text-ink",
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </figcaption>
      <div role="img" aria-label={summary} className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={colors.rule} vertical={false} />
            <ReferenceLine y={0} stroke={colors["rule-2"]} />
            <XAxis
              dataKey="day"
              tickFormatter={(d: string) => formatDate(d).replace(/, \d{4}$/, "")}
              tick={{ fill: colors.muted, fontSize: 12 }}
              stroke={colors.rule}
              minTickGap={24}
            />
            <YAxis
              tickFormatter={(n: number) => `${n.toFixed(0)}%`}
              tick={{ fill: colors.muted, fontSize: 12 }}
              stroke={colors.rule}
              width={44}
            />
            <Tooltip
              contentStyle={{ background: colors["paper-3"], border: `1px solid ${colors["rule-2"]}`, borderRadius: 6 }}
              labelStyle={{ color: colors.ink }}
              labelFormatter={(d) => formatDate(String(d))}
              formatter={(value, name) => [
                formatPercent(Number(value)),
                name === "portfolio" ? "Portfolio" : data.benchmark,
              ]}
            />
            <Line
              type="monotone"
              dataKey="benchmark"
              stroke={colors.muted}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="portfolio"
              stroke={colors.cool}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
