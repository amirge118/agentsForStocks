import { SCORE_RANGE, SCORE_THRESHOLDS } from "@/lib/scoring"
import { cn } from "@/lib/utils"

const span = SCORE_RANGE.max - SCORE_RANGE.min
const pct = (score: number) =>
  ((Math.min(Math.max(score, SCORE_RANGE.min), SCORE_RANGE.max) - SCORE_RANGE.min) / span) * 100

/**
 * The weighted score on its −100…+100 scale, with the HOLD band (between the
 * SELL and BUY thresholds) shaded, so a +16 reads as "only just a BUY".
 */
export function ScoreScale({ score, label = "Weighted score" }: { score: number; label?: string }) {
  const sell = pct(SCORE_THRESHOLDS.sell)
  const buy = pct(SCORE_THRESHOLDS.buy)
  return (
    <div className="space-y-1">
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={SCORE_RANGE.min}
        aria-valuemax={SCORE_RANGE.max}
        aria-valuenow={score}
        aria-valuetext={`${score.toFixed(1)} on a scale from ${SCORE_RANGE.min} to +${SCORE_RANGE.max}; BUY above +${SCORE_THRESHOLDS.buy}, SELL below ${SCORE_THRESHOLDS.sell}`}
        className="relative h-2 rounded-full bg-paper-3"
      >
        <div className="absolute inset-y-0 bg-bad-soft" style={{ left: 0, width: `${sell}%` }} />
        <div className="absolute inset-y-0 bg-ok-soft" style={{ left: `${buy}%`, right: 0 }} />
        <div
          className={cn(
            "absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full",
            score > SCORE_THRESHOLDS.buy ? "bg-ok" : score < SCORE_THRESHOLDS.sell ? "bg-bad" : "bg-ink",
          )}
          style={{ left: `${pct(score)}%` }}
        />
      </div>
      <div className="flex justify-between font-mono text-xs text-muted" aria-hidden>
        <span>{SCORE_RANGE.min}</span>
        <span>{SCORE_THRESHOLDS.sell}</span>
        <span>+{SCORE_THRESHOLDS.buy}</span>
        <span>+{SCORE_RANGE.max}</span>
      </div>
    </div>
  )
}
