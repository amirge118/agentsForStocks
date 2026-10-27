import { consensus } from "@/lib/charts"
import { cn } from "@/lib/utils"
import type { Contribution } from "@/types/api"

const SEGMENTS = [
  { key: "bullish", label: "Bullish", fill: "bg-ok-soft text-ok border-ok/30" },
  { key: "neutral", label: "Neutral", fill: "bg-paper-3 text-ink-2 border-rule" },
  { key: "bearish", label: "Bearish", fill: "bg-bad-soft text-bad border-bad/30" },
] as const

/** How the analysts split, at a glance: one bar, a count in each part. */
export function ConsensusBar({ breakdown }: { breakdown: Contribution[] }) {
  const counts = consensus(breakdown)
  const reported = counts.bullish + counts.neutral + counts.bearish
  if (reported === 0) return null
  const summary = SEGMENTS.map((s) => `${counts[s.key]} ${s.label.toLowerCase()}`).join(", ")
  return (
    <figure className="space-y-2" aria-label="Analyst consensus">
      <figcaption className="flex items-baseline justify-between text-sm">
        <span className="text-muted">Analyst consensus</span>
        <span className="text-xs text-muted">
          {reported} reported{counts.missing > 0 && `, ${counts.missing} missing`}
        </span>
      </figcaption>
      <div className="flex h-8 overflow-hidden rounded-control border border-rule" role="img" aria-label={summary}>
        {SEGMENTS.filter((s) => counts[s.key] > 0).map((s) => (
          <div
            key={s.key}
            className={cn("flex items-center justify-center gap-1.5 border-r last:border-r-0 text-xs", s.fill)}
            style={{ flexGrow: counts[s.key] }}
            title={`${counts[s.key]} ${s.label.toLowerCase()}`}
          >
            <span className="font-mono">{counts[s.key]}</span>
            <span className="hidden sm:inline">{s.label}</span>
          </div>
        ))}
      </div>
    </figure>
  )
}
