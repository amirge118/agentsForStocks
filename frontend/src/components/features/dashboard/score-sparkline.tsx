"use client"

import { Line, LineChart, ReferenceLine, YAxis } from "recharts"

import { scorePoints } from "@/lib/charts"
import { formatScore } from "@/lib/format"
import { useScoreHistory } from "@/lib/hooks/queries"
import { useThemeColors } from "@/lib/hooks/use-theme-colors"
import { SCORE_RANGE } from "@/lib/scoring"

/** The last 30 scores of one symbol, as a small line around zero. */
export function ScoreSparkline({ symbol }: { symbol: string }) {
  const colors = useThemeColors()
  const { data } = useScoreHistory(symbol)
  const points = data ? scorePoints(data).slice(-30) : []
  if (points.length < 2) return <span className="text-xs text-muted">Not enough runs</span>
  const first = points[0]!
  const last = points[points.length - 1]!
  return (
    <span
      role="img"
      aria-label={`Score trend over ${points.length} runs: ${formatScore(first.score)} to ${formatScore(last.score)}`}
      className="inline-block"
    >
      <LineChart width={96} height={28} data={points} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <YAxis hide domain={[SCORE_RANGE.min, SCORE_RANGE.max]} />
        <ReferenceLine y={0} stroke={colors.rule} />
        <Line
          type="monotone"
          dataKey="score"
          stroke={last.score >= first.score ? colors.ok : colors.bad}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </span>
  )
}
