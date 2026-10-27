"use client"

import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { scorePoints } from "@/lib/charts"
import { formatDate, formatScore } from "@/lib/format"
import { useScoreHistory } from "@/lib/hooks/queries"
import { useThemeColors } from "@/lib/hooks/use-theme-colors"
import { SCORE_RANGE, SCORE_THRESHOLDS } from "@/lib/scoring"

/** The weighted score day by day, against the BUY and SELL zones. */
export function ScoreHistoryChart({ symbol }: { symbol: string }) {
  const colors = useThemeColors()
  const { data, isPending, isError, error } = useScoreHistory(symbol)

  if (isPending) return <Loading label="Loading score history" className="h-56" />
  if (isError) return <LoadError what="the score history" error={error} />
  const points = scorePoints(data)
  if (points.length < 2) {
    return <Empty>The score history appears after the second daily run.</Empty>
  }
  const first = points[0]!
  const last = points[points.length - 1]!

  return (
    <figure aria-label="Score history" className="space-y-2">
      <figcaption className="flex items-baseline justify-between text-sm">
        <span className="text-muted">Score over time</span>
        <span className="text-xs text-muted">
          {points.length} runs, {formatDate(first.date)} to {formatDate(last.date)}
        </span>
      </figcaption>
      <div
        role="img"
        aria-label={`Score from ${formatScore(first.score)} on ${formatDate(first.date)} to ${formatScore(last.score)} on ${formatDate(last.date)}`}
        className="h-56"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={colors.rule} vertical={false} />
            <ReferenceArea y1={SCORE_THRESHOLDS.buy} y2={SCORE_RANGE.max} fill={colors.ok} fillOpacity={0.08} />
            <ReferenceArea y1={SCORE_RANGE.min} y2={SCORE_THRESHOLDS.sell} fill={colors.bad} fillOpacity={0.08} />
            <XAxis
              dataKey="date"
              tickFormatter={(d: string) => formatDate(d).replace(/, \d{4}$/, "")}
              tick={{ fill: colors.muted, fontSize: 12 }}
              stroke={colors.rule}
              minTickGap={24}
            />
            <YAxis domain={[SCORE_RANGE.min, SCORE_RANGE.max]} ticks={[-100, -15, 15, 100]} tick={{ fill: colors.muted, fontSize: 12 }} stroke={colors.rule} width={40} />
            <Tooltip
              contentStyle={{ background: colors["paper-3"], border: `1px solid ${colors["rule-2"]}`, borderRadius: 6 }}
              labelStyle={{ color: colors.ink }}
              labelFormatter={(d) => formatDate(String(d))}
              formatter={(value, _name, item) => [`${formatScore(Number(value))} (${item.payload.action})`, "score"]}
            />
            <Line type="monotone" dataKey="score" stroke={colors.ink} strokeWidth={2} dot={{ r: 2, fill: colors.ink }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted">Green zone: BUY (above +{SCORE_THRESHOLDS.buy}). Red zone: SELL (below {SCORE_THRESHOLDS.sell}).</p>
    </figure>
  )
}
