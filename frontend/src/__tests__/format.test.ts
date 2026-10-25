import {
  formatConfidence,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatPercent,
  formatScore,
  toneClasses,
} from "@/lib/format"

describe("finance formatting", () => {
  it("formats currency in USD", () => {
    expect(formatCurrency(1234.5)).toBe("$1,234.50")
  })

  it("signs percentages and scores", () => {
    expect(formatPercent(1.234)).toBe("+1.23%")
    expect(formatPercent(-0.5)).toBe("-0.50%")
    expect(formatPercent(0)).toBe("+0.00%")
    expect(formatScore(42.46)).toBe("+42.5")
    expect(formatScore(-3)).toBe("-3.0")
    expect(formatConfidence(71.6)).toBe("72%")
  })

  it("formats market dates without timezone drift", () => {
    expect(formatDate("2026-10-23")).toBe("Oct 23, 2026")
    expect(formatDateTime("2026-10-23T22:30:00Z")).toMatch(/Oct 23/)
  })

  it("maps gain/loss to the theme tokens", () => {
    expect(toneClasses(1)).toBe("text-green-400 bg-green-400/10")
    expect(toneClasses(-1)).toBe("text-red-400 bg-red-400/10")
    expect(toneClasses(0)).toContain("text-zinc-400")
  })
})
