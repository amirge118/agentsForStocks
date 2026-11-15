/** Pure data shaping for the charts, kept out of components so it is tested directly. */
import type { AgentResult, Contribution, PerformancePoint } from "@/types/api"

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
/** Round ticks around 0 that reach `extent`: at most four on each side. */
export function symmetricTicks(extent: number): number[] {
  const step = [5, 10, 20, 25, 50].find((size) => extent / size <= 4) ?? 100
  const sides = Math.ceil(extent / step)
  return Array.from({ length: sides * 2 + 1 }, (_, i) => (i - sides) * step)
}

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

export const RETURN_RANGES = ["1M", "3M", "YTD", "All"] as const
export type ReturnRange = (typeof RETURN_RANGES)[number]

export interface ReturnPoint {
  day: string
  portfolio: number // percent since the range's first session
  benchmark: number | null
}

/** The first day a range covers, counted back from `last` (an ISO date). */
export function rangeStart(range: ReturnRange, last: string): string {
  if (range === "All") return ""
  const d = new Date(`${last}T00:00:00Z`)
  if (range === "YTD") return `${d.getUTCFullYear()}-01-01`
  d.setUTCMonth(d.getUTCMonth() - (range === "1M" ? 1 : 3))
  return d.toISOString().slice(0, 10)
}

/**
 * The time-weighted return and the benchmark's over a range, both starting at 0% on its
 * first session (growth-of-1 indexes divide, so any session can be the base).
 */
export function returnSeries(series: PerformancePoint[], range: ReturnRange): ReturnPoint[] {
  const last = series.at(-1)
  if (!last) return []
  const from = rangeStart(range, last.day)
  const points = series.filter((p) => p.day >= from)
  const base = points[0]!
  return points.map((p) => ({
    day: p.day,
    portfolio: (p.index / base.index - 1) * 100,
    benchmark: p.benchmark === null || base.benchmark === null ? null : (p.benchmark / base.benchmark - 1) * 100,
  }))
}

export interface Drawdown {
  current: number // percent below the highest point so far (0 at a new high)
  worst: number // the deepest fall from a previous high
  peak: string | null // the day of the high the current fall is measured from
}

/** How far the time-weighted value fell from its highs; null before there are two points. */
export function drawdown(series: PerformancePoint[]): Drawdown | null {
  if (series.length < 2) return null
  let high = series[0]!
  let worst = 0
  for (const p of series) {
    if (p.index > high.index) high = p
    worst = Math.min(worst, (p.index / high.index - 1) * 100)
  }
  const last = series.at(-1)!
  const current = (last.index / high.index - 1) * 100
  return { current, worst, peak: current < 0 ? high.day : null }
}
