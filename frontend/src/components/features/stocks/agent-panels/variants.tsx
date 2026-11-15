/**
 * The agent-specific part of a panel. Each variant parses the stored result with its
 * schema; `null` means "no variant for this payload" and the panel shows only the
 * fields every agent has.
 */
import type { ReactNode } from "react"

import { formatDate, formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  BroadAnalysisResultSchema,
  EarningsResultSchema,
  FinancialHistoryResultSchema,
  FundamentalsResultSchema,
  GrowthResultSchema,
  InstitutionalResultSchema,
  MarketScanResultSchema,
  MoatResultSchema,
  OutcomeReviewResultSchema,
  RiskResultSchema,
  SentimentResultSchema,
  TechnicalsResultSchema,
  ValuationResultSchema,
} from "@/types/api"

import { Metric, SignedBar } from "./metric"

const billions = (n: number) => `$${(n / 1e9).toLocaleString("en-US", { maximumFractionDigits: 1 })}B`

function Valuation({ result }: { result: unknown }) {
  const parsed = ValuationResultSchema.safeParse(result)
  if (!parsed.success) return null
  const v = parsed.data
  const scenarios = (["bear", "base", "bull"] as const).filter((k) => typeof v.dcf[k] === "number" && v.dcf[k]! > 0)
  const values = [...scenarios.map((k) => v.dcf[k]!), v.market_cap].filter((n) => n > 0)
  const max = Math.max(...values)
  return (
    <>
      <dl className="grid grid-cols-2 gap-3">
        <Metric
          label="Margin of safety"
          hint="How far the market value sits below our estimate of what the company is worth. Positive means undervalued."
          value={formatPercent(v.margin_of_safety * 100)}
          tone={v.margin_of_safety >= 0 ? "ok" : "bad"}
        />
        <Metric label="Intrinsic value" hint="The average of the valuation methods that produced a figure." value={billions(v.avg_intrinsic_value)} />
        {typeof v.implied_growth === "number" && typeof v.growth_rate === "number" && (
          <Metric
            label="Growth priced in"
            hint="The yearly growth (years 1-5) the market value implies, next to the company's own revenue growth. Far above it means the price expects more than the record shows."
            value={`${formatPercent(v.implied_growth * 100)} vs ${formatPercent(v.growth_rate * 100)}`}
            tone={v.implied_growth > v.growth_rate ? "bad" : "ok"}
          />
        )}
      </dl>
      {scenarios.length > 0 && max > 0 && (
        <div className="space-y-1.5" aria-label="DCF scenarios against the market cap">
          {scenarios.map((k) => (
            <div key={k} className="grid grid-cols-[3rem_1fr_4.5rem] items-center gap-2 text-xs">
              <span className="text-muted capitalize">{k}</span>
              <div className="h-1.5 rounded-full bg-paper-3" aria-hidden>
                <div
                  className={cn("h-full rounded-full", v.dcf[k]! >= v.market_cap ? "bg-ok" : "bg-bad")}
                  style={{ width: `${(v.dcf[k]! / max) * 100}%` }}
                />
              </div>
              <span className="text-right font-mono">{billions(v.dcf[k]!)}</span>
            </div>
          ))}
          <div className="grid grid-cols-[3rem_1fr_4.5rem] items-center gap-2 text-xs">
            <span className="text-muted">Market</span>
            <div className="h-1.5 rounded-full bg-paper-3" aria-hidden>
              <div className="h-full rounded-full bg-ink-2" style={{ width: `${(v.market_cap / max) * 100}%` }} />
            </div>
            <span className="text-right font-mono">{billions(v.market_cap)}</span>
          </div>
        </div>
      )}
    </>
  )
}

function Technicals({ result }: { result: unknown }) {
  const parsed = TechnicalsResultSchema.safeParse(result)
  if (!parsed.success) return null
  const t = parsed.data
  return (
    <div className="space-y-1.5" aria-label="Strategy signals from -1 to +1">
      {Object.entries(t.strategies).map(([name, value]) => (
        <SignedBar key={name} label={name} value={value} />
      ))}
      <div className="border-t border-rule pt-1.5">
        <SignedBar label="composite" value={t.composite} />
      </div>
    </div>
  )
}

function Fundamentals({ result }: { result: unknown }) {
  const parsed = FundamentalsResultSchema.safeParse(result)
  if (!parsed.success) return null
  return (
    <ul className="space-y-1 text-xs" aria-label="Fundamental factors">
      {parsed.data.factors.map((f) => (
        <li key={f.name} className="flex items-baseline gap-2">
          <span
            aria-label={f.signal}
            className={cn("font-mono", f.signal === "bullish" ? "text-ok" : f.signal === "bearish" ? "text-bad" : "text-muted")}
          >
            {f.signal === "bullish" ? "✓" : f.signal === "bearish" ? "✗" : "○"}
          </span>
          <span className="text-ink-2 capitalize">{f.name.replace(/_/g, " ")}</span>
          <span className="ml-auto truncate text-muted">{f.detail}</span>
        </li>
      ))}
    </ul>
  )
}

function Earnings({ result }: { result: unknown }) {
  const parsed = EarningsResultSchema.safeParse(result)
  if (!parsed.success) return null
  const e = parsed.data
  return (
    <dl className="grid grid-cols-3 gap-3">
      <Metric
        label="Beat rate"
        hint={`Share of the last ${e.quarters_analyzed} quarters where reported earnings beat the analysts' estimate.`}
        value={`${Math.round(e.beat_rate * 100)}%`}
        tone={e.beat_rate >= 0.5 ? "ok" : "bad"}
      />
      <Metric label="Avg surprise" hint="Average gap between reported and estimated earnings per share." value={formatPercent(e.avg_surprise_pct)} />
      <Metric label="Next report" hint="The next scheduled earnings date." value={e.next_earnings} />
    </dl>
  )
}

function Risk({ result }: { result: unknown }) {
  const parsed = RiskResultSchema.safeParse(result)
  if (!parsed.success) return null
  const r = parsed.data
  return (
    <dl className="grid grid-cols-3 gap-3">
      <Metric
        label="Debt / equity"
        hint="Debt for every dollar of shareholder equity. Above 3 is heavy."
        value={r.debt_to_equity?.toFixed(2) ?? "N/A"}
        tone={r.debt_to_equity != null && r.debt_to_equity > 3 ? "bad" : undefined}
      />
      <Metric
        label="Current ratio"
        hint="Short-term assets over short-term debts. Above 1.5 is healthy, below 1.0 is stress."
        value={r.current_ratio?.toFixed(2) ?? "N/A"}
        tone={r.current_ratio == null ? undefined : r.current_ratio >= 1.5 ? "ok" : r.current_ratio < 1 ? "bad" : undefined}
      />
      <Metric label="Beta" hint="How much the stock moves with the market: 1 moves with it, above 1 swings harder." value={r.beta?.toFixed(2) ?? "N/A"} />
    </dl>
  )
}

function Sentiment({ result }: { result: unknown }) {
  const parsed = SentimentResultSchema.safeParse(result)
  if (!parsed.success) return null
  const s = parsed.data
  return (
    <dl className="grid grid-cols-2 gap-3">
      {(["insider", "news"] as const).map((k) => (
        <Metric
          key={k}
          label={k === "insider" ? "Insider trades (30%)" : "News (70%)"}
          hint={s[k].detail}
          value={`${s[k].signal} ${Math.round(s[k].confidence)}%`}
          tone={s[k].signal === "bullish" ? "ok" : s[k].signal === "bearish" ? "bad" : undefined}
        />
      ))}
    </dl>
  )
}

/** 0.157 → "15.7%": a share, not a change, so no sign */
const share = (fraction: number | null) => (fraction == null ? "N/A" : `${(fraction * 100).toFixed(1)}%`)
const signTone = (n: number): "ok" | "bad" => (n >= 0 ? "ok" : "bad")

function FinancialHistory({ result }: { result: unknown }) {
  const parsed = FinancialHistoryResultSchema.safeParse(result)
  if (!parsed.success) return null
  const f = parsed.data
  const rows = [
    ["Revenue", f.revenue_cagr, "Sales"],
    ["Net income", f.net_income_cagr, "Profit after every cost and tax"],
    ["Free cash flow", f.fcf_cagr, "Cash left after running and investing in the business"],
  ] as const
  return (
    <dl className="grid grid-cols-3 gap-3">
      {rows.map(([label, value, what]) => (
        <Metric
          key={label}
          label={label}
          hint={`${what}: average growth a year over the reported years.`}
          value={`${formatPercent(value * 100)}/yr`}
          tone={signTone(value)}
        />
      ))}
    </dl>
  )
}

function Moat({ result }: { result: unknown }) {
  const parsed = MoatResultSchema.safeParse(result)
  if (!parsed.success) return null
  const m = parsed.data
  const swing = Math.sqrt(Math.max(0, m.gross_margin_variance)) * 100
  return (
    <>
      <dl className="grid grid-cols-3 gap-3">
        <Metric
          label="Gross margin"
          hint="Share of each sale left after the direct cost of making it, averaged over five years. High and steady points to pricing power."
          value={share(m.avg_gross_margin)}
        />
        <Metric
          label="Margin swing"
          hint="How much the gross margin moved from year to year (standard deviation). Small means the company holds its prices."
          value={`±${swing.toFixed(1)} pts`}
        />
        <Metric
          label="Intangibles"
          hint="Brands, patents and goodwill as a share of total assets."
          value={share(m.intangibles_pct)}
        />
      </dl>
      {m.moat_keywords.length > 0 && <Chips label="Moat sources named in the filings" items={m.moat_keywords} />}
    </>
  )
}

function Institutional({ result }: { result: unknown }) {
  const parsed = InstitutionalResultSchema.safeParse(result)
  if (!parsed.success) return null
  const i = parsed.data
  const change = i.net_share_change
  return (
    <dl className="grid grid-cols-3 gap-3">
      <Metric
        label="Held by funds"
        hint="Share of all shares owned by institutions (funds, banks, insurers)."
        value={share(i.institutional_pct)}
      />
      <Metric
        label="Top 5 hold"
        hint="Of the listed institutional holdings, the share owned by the five largest holders."
        value={share(i.top5_concentration)}
      />
      <Metric
        label="Last quarter"
        hint="Whether the largest holders bought (accumulating) or sold (distributing) shares in their last filings."
        value={change == null ? "N/A" : `${change >= 0 ? "+" : "−"}${compact(Math.abs(change))} sh`}
        tone={change == null || change === 0 ? undefined : signTone(change)}
      />
    </dl>
  )
}

function Growth({ result }: { result: unknown }) {
  const parsed = GrowthResultSchema.safeParse(result)
  if (!parsed.success) return null
  const g = parsed.data
  const source = g.transcript_available
    ? "Earnings call"
    : g.earnings_release_used
      ? "Earnings release"
      : "None"
  return (
    <dl className="grid grid-cols-2 gap-3">
      <Metric
        label="Analysts covering"
        hint="How many analysts publish revenue and earnings estimates for the company. Few means the forecast is thin."
        value={g.analyst_coverage}
      />
      <Metric
        label="Management's words"
        hint="What the agent read from management about the outlook: the earnings call transcript, or the earnings release filed with the SEC."
        value={<span className="font-sans">{source}</span>}
      />
    </dl>
  )
}

function BroadAnalysis({ result }: { result: unknown }) {
  const parsed = BroadAnalysisResultSchema.safeParse(result)
  if (!parsed.success) return null
  const b = parsed.data
  return (
    <dl className="grid grid-cols-2 gap-3">
      <Metric label="Industry" hint={`Sector: ${b.sector}.`} value={<span className="font-sans">{b.industry}</span>} />
      <Metric
        label="Market cap"
        hint="What the market values the whole company at."
        value={b.market_cap_b == null ? "N/A" : billions(b.market_cap_b * 1e9)}
      />
    </dl>
  )
}

function MarketScanner({ result }: { result: unknown }) {
  const parsed = MarketScanResultSchema.safeParse(result)
  if (!parsed.success) return null
  const s = parsed.data
  const vsAverage = s.metrics.price_vs_sma20_pct
  return (
    <>
      <dl className="grid grid-cols-2 gap-3">
        <Metric
          label="Short-term risk"
          hint="The scanner's read of how risky the stock looks right now, from its price and volume."
          value={<span className="font-sans capitalize">{s.risk_level}</span>}
          tone={s.risk_level === "low" ? "ok" : s.risk_level === "high" ? "bad" : undefined}
        />
        {typeof vsAverage === "number" && (
          <Metric
            label="vs 20-day average"
            hint="Today's price against its average over the last 20 trading days."
            value={formatPercent(vsAverage)}
            tone={signTone(vsAverage)}
          />
        )}
      </dl>
      {s.observations.length > 0 && <Notes items={s.observations} />}
    </>
  )
}

function OutcomeReview({ result }: { result: unknown }) {
  const parsed = OutcomeReviewResultSchema.safeParse(result)
  if (!parsed.success) return null
  const lessons = parsed.data.lessons
  if (lessons.length === 0) {
    return <p className="text-xs text-muted">No past call on this stock has settled yet, so there is nothing to learn from.</p>
  }
  return (
    <ul className="space-y-2 text-xs">
      {lessons.map((l) => (
        <li key={`${l.decision_date}-${l.horizon_days}`} className="space-y-0.5">
          <p className="text-muted">
            {formatDate(l.decision_date)} call, {l.signal}, {l.horizon_days} sessions:{" "}
            <span className={cn("font-mono", l.alpha >= 0 ? "text-ok" : "text-bad")}>{formatPercent(l.alpha * 100)}</span> vs{" "}
            {l.benchmark}
          </p>
          <p className="text-ink-2">{l.text}</p>
        </li>
      ))}
    </ul>
  )
}

function Chips({ label, items }: { label: string; items: string[] }) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item} className="rounded-chip bg-paper-3 px-1.5 py-0.5 text-xs text-ink-2">
          {item}
        </li>
      ))}
    </ul>
  )
}

function Notes({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-2 marker:text-muted">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  )
}

const compact = (n: number) => n.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 })

const VARIANTS: Record<string, (props: { result: unknown }) => ReactNode> = {
  valuation: Valuation,
  technicals: Technicals,
  fundamentals: Fundamentals,
  earnings: Earnings,
  risk: Risk,
  sentiment: Sentiment,
  financial_history: FinancialHistory,
  moat: Moat,
  institutional: Institutional,
  growth: Growth,
  broad_analysis: BroadAnalysis,
  market_scanner: MarketScanner,
  outcome_review: OutcomeReview,
}

export function AgentDetail({ agent, result }: { agent: string; result: unknown }) {
  const Variant = VARIANTS[agent]
  return Variant ? <Variant result={result} /> : null
}
