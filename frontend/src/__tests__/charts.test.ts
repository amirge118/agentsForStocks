import {
  actionMarkers,
  consensus,
  drawdown,
  isStale,
  marketDaysBetween,
  priceSeries,
  rangeChange,
  rangeStart,
  returnSeries,
  runningScore,
  scorePoints,
  symmetricTicks,
  waterfall,
} from "@/lib/charts"
import { latestPerAgent } from "@/lib/hooks/queries"
import { agentResults, performance, priceHistory, recommendation } from "@/test/fixtures"

describe("chart data shaping", () => {
  it("counts the consensus, keeping missing analysts apart", () => {
    expect(consensus(recommendation.agent_breakdown)).toEqual({ bullish: 1, neutral: 0, bearish: 1, missing: 1 })
  })

  it("builds waterfall steps largest first, from 0 to the total, without missing analysts", () => {
    expect(waterfall(recommendation.agent_breakdown)).toEqual([
      { agent: "moat", contribution: 12, from: 0, to: 12 },
      { agent: "risk", contribution: -6, from: 12, to: 6 },
    ])
  })

  it("counts market days and flags a stale recommendation", () => {
    expect(marketDaysBetween("2026-10-23", "2026-10-26")).toBe(1) // Friday → Monday
    expect(marketDaysBetween("2026-10-20", "2026-10-23")).toBe(3)
    expect(isStale("2026-10-23", new Date("2026-10-26T15:00:00Z"))).toBe(false)
    expect(isStale("2026-10-21", new Date("2026-10-26T15:00:00Z"))).toBe(true)
  })

  it("keeps the newest result per agent", () => {
    const latest = latestPerAgent(agentResults)
    expect(latest.get("moat")?.run_date).toBe("2026-10-23")
    expect(latest.get("recommendation")?.result.action).toBe("BUY")
  })

  it("turns recommendation rows into score points and BUY / SELL markers", () => {
    const rows = agentResults.filter((r) => r.agent_type === "recommendation").reverse()
    const points = scorePoints([...rows, { ...rows[0]!, result: { action: "BUY" } }])
    expect(points.map((p) => p.score)).toEqual([-20, 3, 42.5])
    expect(actionMarkers(points).map((p) => p.action)).toEqual(["SELL", "BUY"])
  })

  it("splits price bars into series and measures the range change", () => {
    const series = priceSeries([...priceHistory.bars, { ...priceHistory.bars[0]!, date: "2026-10-26", close: 200, sma20: null, volume: null }])
    expect(series.close).toHaveLength(4)
    expect(series.sma20).toHaveLength(3)
    expect(series.volume.map((v) => v.up)).toEqual([true, true, true])
    expect(rangeChange(priceHistory.bars)).toBeCloseTo(2.1739, 3)
    expect(rangeChange(priceHistory.bars.slice(0, 1))).toBeNull()
  })
})

describe("runningScore", () => {
  it("adds each analyst in story order, skipping those not weighted or missing", () => {
    const steps = runningScore(["technicals", "moat", "institutional", "risk"], recommendation.agent_breakdown)
    expect(steps).toEqual([
      { agent: "technicals", contribution: null, total: 0 },
      { agent: "moat", contribution: 12, total: 12 },
      { agent: "institutional", contribution: null, total: 12 },
      { agent: "risk", contribution: -6, total: 6 },
    ])
  })
})

describe("symmetricTicks", () => {
  it("gives round ticks around 0 that reach the extent", () => {
    expect(symmetricTicks(10)).toEqual([-10, -5, 0, 5, 10])
    expect(symmetricTicks(31)).toEqual([-40, -30, -20, -10, 0, 10, 20, 30, 40])
    expect(symmetricTicks(70.5)).toEqual([-80, -60, -40, -20, 0, 20, 40, 60, 80])
    expect(symmetricTicks(250)).toEqual([-300, -200, -100, 0, 100, 200, 300])
  })
})

describe("returnSeries", () => {
  it("starts the portfolio and the benchmark at 0% on the range's first session", () => {
    const all = returnSeries(performance.series, "All")
    expect(all.map((p) => p.day)).toEqual(["2026-11-02", "2026-11-03", "2026-11-04"])
    expect(all[0]).toEqual({ day: "2026-11-02", portfolio: 0, benchmark: 0 })
    expect(all[2]!.portfolio).toBeCloseTo(1.99)
    expect(all[2]!.benchmark).toBeCloseTo((1.01 / 1.002 - 1) * 100)
  })

  it("rebases a shorter range, and keeps a missing benchmark missing", () => {
    const series = [
      { day: "2026-08-01", value: 1, flow: 0, index: 1, benchmark: null },
      { day: "2026-10-15", value: 1, flow: 0, index: 1.1, benchmark: 1 },
      { day: "2026-11-04", value: 1, flow: 0, index: 1.21, benchmark: 1.05 },
    ]
    const month = returnSeries(series, "1M")
    expect(month.map((p) => p.day)).toEqual(["2026-10-15", "2026-11-04"])
    expect(month[1]!.portfolio).toBeCloseTo(10)
    expect(month[1]!.benchmark).toBeCloseTo(5)
    expect(returnSeries(series, "All")[2]!.benchmark).toBeNull()
    expect(returnSeries([], "All")).toEqual([])
  })

  it("counts each range back from the last day", () => {
    expect(rangeStart("1M", "2026-11-04")).toBe("2026-10-04")
    expect(rangeStart("3M", "2026-11-04")).toBe("2026-08-04")
    expect(rangeStart("YTD", "2026-11-04")).toBe("2026-01-01")
    expect(rangeStart("All", "2026-11-04")).toBe("")
  })
})

describe("drawdown", () => {
  const point = (day: string, index: number) => ({ day, value: 1, flow: 0, index, benchmark: null })

  it("measures the fall from the highest point so far, and the worst one", () => {
    const series = [point("d1", 1), point("d2", 1.2), point("d3", 0.9), point("d4", 1.08)]
    const fall = drawdown(series)!
    expect(fall.current).toBeCloseTo(-10)
    expect(fall.worst).toBeCloseTo(-25)
    expect(fall.peak).toBe("d2")
  })

  it("is 0 at a new high, and needs two points", () => {
    expect(drawdown([point("d1", 1), point("d2", 1.1)])).toEqual({ current: 0, worst: 0, peak: null })
    expect(drawdown([point("d1", 1)])).toBeNull()
  })
})
