/**
 * The agent-specific part of a panel. Each variant parses the stored result with its
 * schema; `null` means "no variant for this payload" and the panel shows only the
 * fields every agent has.
 */
import type { ReactNode } from "react"

import { formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  EarningsResultSchema,
  FundamentalsResultSchema,
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

const VARIANTS: Record<string, (props: { result: unknown }) => ReactNode> = {
  valuation: Valuation,
  technicals: Technicals,
  fundamentals: Fundamentals,
  earnings: Earnings,
  risk: Risk,
  sentiment: Sentiment,
}

export function AgentDetail({ agent, result }: { agent: string; result: unknown }) {
  const Variant = VARIANTS[agent]
  return Variant ? <Variant result={result} /> : null
}
