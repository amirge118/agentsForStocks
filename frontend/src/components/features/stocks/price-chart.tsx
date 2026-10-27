"use client"

import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useEffect, useMemo, useRef } from "react"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { ApiError } from "@/lib/api/client"
import { actionMarkers, priceSeries, rangeChange, scorePoints, type PriceSeries, type ScorePoint } from "@/lib/charts"
import { formatCurrency, formatPercent } from "@/lib/format"
import { usePrices, useScoreHistory } from "@/lib/hooks/queries"
import { readThemeColors, type ThemeColors } from "@/lib/hooks/use-theme-colors"
import { cn } from "@/lib/utils"
import { PriceRangeSchema, type PriceRange } from "@/types/api"

const RANGES: PriceRange[] = ["1M", "3M", "6M", "1Y"]

/** The range lives in the URL (?range=), so a shared link opens on the same view. */
function useRange(): [PriceRange, (range: PriceRange) => void] {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const parsed = PriceRangeSchema.safeParse(params?.get("range"))
  const range = parsed.success ? parsed.data : "6M"
  const setRange = (next: PriceRange) => {
    const query = new URLSearchParams(params?.toString())
    query.set("range", next)
    router.replace(`${pathname}?${query.toString()}`, { scroll: false })
  }
  return [range, setRange]
}

/** Close with SMA20 / SMA50, a volume pane and an RSI pane; markers on BUY / SELL days. */
export function PriceChart({ symbol }: { symbol: string }) {
  const [range, setRange] = useRange()
  const prices = usePrices(symbol, range)
  const history = useScoreHistory(symbol)
  const markers = useMemo(() => (history.data ? actionMarkers(scorePoints(history.data)) : []), [history.data])
  const series = useMemo(() => priceSeries(prices.data?.bars ?? []), [prices.data])

  const bars = prices.data?.bars ?? []
  const change = rangeChange(bars)
  const last = bars.at(-1)

  return (
    <section aria-labelledby="price-chart-title" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h2 id="price-chart-title" className="text-base">
            Price
          </h2>
          {last && <span className="font-mono text-lg">{formatCurrency(last.close)}</span>}
          {change !== null && (
            <span className="text-sm text-muted">
              <span className={cn("font-mono", change >= 0 ? "text-ok" : "text-bad")}>{formatPercent(change)}</span> over{" "}
              <span className="font-mono">{range}</span>
            </span>
          )}
        </div>
        <div role="group" aria-label="Price range" className="flex rounded-control border border-rule bg-paper-3 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={r === range}
              onClick={() => setRange(r)}
              className={cn(
                "rounded-chip px-2.5 py-1 font-mono text-xs transition-colors duration-[var(--dur-micro)]",
                r === range ? "bg-paper-2 text-ink" : "text-muted hover:text-ink",
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      {prices.isPending ? (
        <Loading label="Loading prices" className="h-80" />
      ) : prices.isError ? (
        prices.error instanceof ApiError && prices.error.status === 502 ? (
          <Empty>Price data is unavailable right now. Try again in a few minutes.</Empty>
        ) : (
          <LoadError what="prices" error={prices.error} />
        )
      ) : bars.length === 0 ? (
        <Empty>No price data for {symbol}.</Empty>
      ) : (
        <PriceCanvas series={series} markers={markers} label={`${symbol} price, ${range}`} />
      )}
      <p className="text-xs text-muted">
        <span className="text-ink-2">Close</span>, <span className="text-cool">SMA 20</span>,{" "}
        <span className="text-accent">SMA 50</span>; RSI 14 below, with the 30 / 70 lines. ▲ BUY and ▼ SELL mark the
        days the pipeline recommended them.
      </p>
    </section>
  )
}

function PriceCanvas({ series, markers, label }: { series: PriceSeries; markers: ScorePoint[]; label: string }) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = container.current
    if (!el) return
    let dispose = () => {}
    let cancelled = false
    void import("lightweight-charts").then((lw) => {
      if (cancelled) return
      const c: ThemeColors = readThemeColors()
      const chart = lw.createChart(el, {
        autoSize: true,
        layout: {
          background: { color: "transparent" },
          textColor: c.muted,
          fontFamily: getComputedStyle(el).fontFamily,
          panes: { separatorColor: c.rule },
        },
        grid: { vertLines: { color: c.rule }, horzLines: { color: c.rule } },
        rightPriceScale: { borderColor: c.rule },
        timeScale: { borderColor: c.rule },
        crosshair: { mode: lw.CrosshairMode.Magnet },
      })
      const close = chart.addSeries(lw.LineSeries, { color: c.ink, lineWidth: 2, priceLineVisible: false })
      close.setData(series.close)
      chart.addSeries(lw.LineSeries, { color: c.cool, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(series.sma20)
      chart.addSeries(lw.LineSeries, { color: c.accent, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(series.sma50)
      lw.createSeriesMarkers(
        close,
        markers.map((m) => ({
          time: m.date,
          position: m.action === "BUY" ? ("belowBar" as const) : ("aboveBar" as const),
          shape: m.action === "BUY" ? ("arrowUp" as const) : ("arrowDown" as const),
          color: m.action === "BUY" ? c.ok : c.bad,
          text: m.action,
        })),
      )
      chart
        .addSeries(lw.HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1)
        .setData(series.volume.map((v) => ({ time: v.time, value: v.value, color: v.up ? c.ok : c.bad })))
      const rsi = chart.addSeries(lw.LineSeries, { color: c["ink-2"], lineWidth: 1, priceLineVisible: false }, 2)
      rsi.setData(series.rsi14)
      for (const level of [30, 70]) {
        rsi.createPriceLine({ price: level, color: c["rule-2"], lineWidth: 1, lineStyle: lw.LineStyle.Dashed, axisLabelVisible: true })
      }
      const panes = chart.panes()
      panes[0]?.setStretchFactor(4)
      panes[1]?.setStretchFactor(1)
      panes[2]?.setStretchFactor(1.4)
      chart.timeScale().fitContent()
      dispose = () => chart.remove()
    })
    return () => {
      cancelled = true
      dispose()
    }
  }, [series, markers])

  return <div ref={container} role="img" aria-label={label} className="h-96 w-full" data-testid="price-chart" />
}
