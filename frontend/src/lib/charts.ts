/** Pure data shaping for the symbol page's charts, kept out of components so it is tested directly. */
import type { AgentResult, Contribution } from "@/types/api"

export interface Consensus {
  bullish: number
  neutral: number
  bearish: number
  missing: number
}

/** How many analysts landed on each signal (a missing analyst is counted apart). */
export function consensus(breakdown: Contribution[]): Consensus {
  const counts: Consensus = { bullish: 0, neutral: 0, bearish: 0, missing: 0 }
  for (const c of breakdown) {
    if (c.signal === "bullish" || c.signal === "bearish" || c.signal === "neutral") counts[c.signal] += 1
    else counts.missing += 1
  }
  return counts
}

export interface WaterfallStep {
  agent: string
  contribution: number
  /** Running total before and after this agent */
  from: number
  to: number
}

/**
 * Steps from 0 to the weighted score, one per analyst that reported, largest
 * effect first. Missing analysts are left out (they add nothing).
 */
export function waterfall(breakdown: Contribution[]): WaterfallStep[] {
  const reported = breakdown
    .filter((c) => c.signal !== "missing")
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
  let total = 0
  return reported.map((c) => {
    const from = total
    total += c.contribution
    return { agent: c.agent, contribution: c.contribution, from, to: total }
  })
}

export interface RunningStep {
  agent: string
  /** null when the analyst is not weighted in the score, or did not report */
  contribution: number | null
  /** Score after this analyst */
  total: number
}

/**
 * The score as it builds up, in the order the story tells the analysts. Its last
 * total is the sum of the contributions, which is the weighted score.
 */
export function runningScore(order: string[], breakdown: Contribution[]): RunningStep[] {
  const counted = new Map(breakdown.filter((c) => c.signal !== "missing").map((c) => [c.agent, c.contribution]))
  let total = 0
  return order.map((agent) => {
    const contribution = counted.get(agent) ?? null
    total += contribution ?? 0
    return { agent, contribution, total }
  })
}

/** Whole market days between two ISO dates, skipping weekends. */
export function marketDaysBetween(fromIso: string, toIso: string): number {
  const from = new Date(`${fromIso.slice(0, 10)}T00:00:00Z`)
  const to = new Date(`${toIso.slice(0, 10)}T00:00:00Z`)
  let days = 0
  for (let d = new Date(from); d < to; d.setUTCDate(d.getUTCDate() + 1)) {
    const next = new Date(d)
    next.setUTCDate(next.getUTCDate() + 1)
    const weekday = next.getUTCDay()
    if (weekday !== 0 && weekday !== 6) days += 1
  }
  return days
}

/** A recommendation is stale once more than one market day has passed since its run date. */
export function isStale(runDate: string, now: Date = new Date()): boolean {
  return marketDaysBetween(runDate, now.toISOString()) > 1
}

export interface ScorePoint {
  date: string
  score: number
  action: string
}

/** Score history points from stored recommendation results; rows without a score are skipped. */
export function scorePoints(rows: AgentResult[]): ScorePoint[] {
  const points: ScorePoint[] = []
  for (const row of rows) {
    const score = row.result.weighted_score
    const action = row.result.action
    if (typeof score === "number" && typeof action === "string") {
      points.push({ date: row.run_date, score, action })
    }
  }
  return points
}

/** BUY / SELL days for the price chart's markers (HOLD days get none). */
export function actionMarkers(points: ScorePoint[]): ScorePoint[] {
  return points.filter((p) => p.action === "BUY" || p.action === "SELL")
}

export interface LinePoint {
  time: string
  value: number
}

export interface PriceSeries {
  close: LinePoint[]
  sma20: LinePoint[]
  sma50: LinePoint[]
  rsi14: LinePoint[]
  volume: (LinePoint & { up: boolean })[]
}

/** Split price bars into the chart's series, dropping null indicator values (warm-up). */
export function priceSeries(
  bars: { date: string; close: number; volume: number | null; sma20: number | null; sma50: number | null; rsi14: number | null }[],
): PriceSeries {
  const series: PriceSeries = { close: [], sma20: [], sma50: [], rsi14: [], volume: [] }
  bars.forEach((bar, i) => {
    const time = bar.date
    series.close.push({ time, value: bar.close })
    if (bar.sma20 !== null) series.sma20.push({ time, value: bar.sma20 })
    if (bar.sma50 !== null) series.sma50.push({ time, value: bar.sma50 })
    if (bar.rsi14 !== null) series.rsi14.push({ time, value: bar.rsi14 })
    if (bar.volume !== null) {
      const prev = i > 0 ? bars[i - 1]!.close : bar.close
      series.volume.push({ time, value: bar.volume, up: bar.close >= prev })
    }
  })
  return series
}

/** Change from the first to the last close of the range, in percent (null without two bars). */
export function rangeChange(bars: { close: number }[]): number | null {
  if (bars.length < 2) return null
  const first = bars[0]!.close
  const last = bars[bars.length - 1]!.close
  return first === 0 ? null : ((last - first) / first) * 100
}
