import {
  actionMarkers,
  consensus,
  isStale,
  marketDaysBetween,
  priceSeries,
  rangeChange,
  runningScore,
  scorePoints,
  waterfall,
} from "@/lib/charts"
import { latestPerAgent } from "@/lib/hooks/queries"
import { agentResults, priceHistory, recommendation } from "@/test/fixtures"

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
