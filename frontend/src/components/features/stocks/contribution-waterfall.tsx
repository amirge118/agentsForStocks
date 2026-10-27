"use client"

import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { waterfall } from "@/lib/charts"
import { formatScore } from "@/lib/format"
import { useThemeColors } from "@/lib/hooks/use-theme-colors"
import type { Contribution } from "@/types/api"

/**
 * Why the score is what it is: from 0, each analyst's weighted contribution
 * (largest first) adds or subtracts, ending on the weighted score.
 */
export function ContributionWaterfall({
  breakdown,
  score,
}: {
  breakdown: Contribution[]
  score: number
}) {
  const colors = useThemeColors()
  const steps = waterfall(breakdown)
  if (steps.length === 0) return null
  const data = steps.map((s) => ({ ...s, range: [s.from, s.to] as [number, number] }))
  const extent = Math.max(10, ...steps.flatMap((s) => [Math.abs(s.from), Math.abs(s.to)]))
  const summary = steps.map((s) => `${s.agent} ${formatScore(s.contribution)}`).join(", ")

  return (
    <figure aria-label="Contribution to the score" className="space-y-2">
      <figcaption className="flex items-baseline justify-between text-sm">
        <span className="text-muted">What moved the score</span>
        <span className="text-xs text-muted">
          Total <span className="font-mono">{formatScore(score)}</span>
        </span>
      </figcaption>
      <div role="img" aria-label={`Contributions: ${summary}; total ${formatScore(score)}`} style={{ height: 36 * data.length + 40 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
            <XAxis
              type="number"
              domain={[-Math.ceil(extent), Math.ceil(extent)]}
              tick={{ fill: colors.muted, fontSize: 12 }}
              stroke={colors.rule}
            />
            <YAxis
              type="category"
              dataKey="agent"
              width={120}
              tick={{ fill: colors["ink-2"], fontSize: 13 }}
              stroke={colors.rule}
            />
            <ReferenceLine x={0} stroke={colors["rule-2"]} />
            <Tooltip
              cursor={{ fill: colors["paper-3"] }}
              contentStyle={{ background: colors["paper-3"], border: `1px solid ${colors["rule-2"]}`, borderRadius: 6 }}
              labelStyle={{ color: colors.ink }}
              formatter={(_value, _name, item) => [formatScore(item.payload.contribution), "contribution"]}
            />
            <Bar dataKey="range" isAnimationActive={false} radius={2}>
              {data.map((d) => (
                <Cell key={d.agent} fill={d.contribution >= 0 ? colors.ok : colors.bad} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
