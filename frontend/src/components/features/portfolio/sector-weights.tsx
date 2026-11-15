"use client"

import { useState } from "react"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { Button } from "@/components/ui/button"
import { formatCurrency, formatShare } from "@/lib/format"
import { useExposure, useSectorTargets } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import type { SectorShare, SectorTargetIn } from "@/types/api"

const TARGET = /^\d{1,3}(\.\d{1,2})?$/

/** A target is a percent from 0 to 100, up to two decimals; empty means no target. */
export function parseTargets(drafts: Record<string, string>): SectorTargetIn[] | string {
  const targets: SectorTargetIn[] = []
  for (const [sector, raw] of Object.entries(drafts)) {
    const value = raw.trim()
    if (value === "") continue
    if (!TARGET.test(value) || Number(value) > 100) return `${sector}: a percent from 0 to 100.`
    targets.push({ sector, target_pct: value })
  }
  return targets
}

/** Each sector's share of the portfolio, against the target set for it (drift in points). */
export function SectorWeights() {
  const { data, isPending, isError, error } = useExposure()
  if (isPending) return <Loading label="Loading sectors" className="h-40" />
  if (isError) return <LoadError what="the sectors" error={error} />
  if (data.sectors.length <= 1) {
    return <Empty>Sector weights appear once the portfolio holds something.</Empty>
  }
  // Keyed by the saved targets, so the form starts over when they change
  const key = data.sectors.map((s) => `${s.sector}=${s.target ?? ""}`).join("|")
  return <SectorForm key={key} sectors={data.sectors} />
}

function SectorForm({ sectors }: { sectors: SectorShare[] }) {
  const save = useSectorTargets()
  const [drafts, setDrafts] = useState<Record<string, string>>(() =>
    Object.fromEntries(sectors.map((s) => [s.sector, s.target === null ? "" : String(s.target)])),
  )
  const [problem, setProblem] = useState<string | null>(null)

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        const targets = parseTargets(drafts)
        if (typeof targets === "string") return setProblem(targets)
        setProblem(null)
        save.mutate(targets)
      }}
    >
      <ul className="space-y-3">
        {sectors.map((s) => (
          <SectorRow
            key={s.sector}
            share={s}
            draft={drafts[s.sector] ?? ""}
            onDraft={(value) => setDrafts((d) => ({ ...d, [s.sector]: value }))}
          />
        ))}
      </ul>
      {problem && (
        <p role="alert" className="text-xs text-bad">
          {problem}
        </p>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted">Targets are optional and don&apos;t have to add up to 100%.</p>
        <Button type="submit" size="sm" variant="outline" disabled={save.isPending}>
          Save targets
        </Button>
      </div>
    </form>
  )
}

function SectorRow({ share: s, draft, onDraft }: { share: SectorShare; draft: string; onDraft: (v: string) => void }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-2 text-sm">
          <span className="truncate">{s.sector}</span>
          <span className="font-mono tabular-nums">{formatShare(s.weight)}</span>
        </div>
        <div className="relative mt-1 h-1.5 rounded-chip bg-paper-3" aria-hidden>
          <div className="h-full rounded-chip bg-cool" style={{ width: `${Math.min(s.weight, 100)}%` }} />
          {s.target !== null && (
            <div className="absolute -top-0.5 h-2.5 w-px bg-ink" style={{ left: `${Math.min(s.target, 100)}%` }} />
          )}
        </div>
        <p className="mt-1 truncate text-xs text-muted">
          <span className="font-mono">{formatCurrency(s.value)}</span>
          {s.symbols.length > 0 && ` · ${s.symbols.join(", ")}`}
          {s.drift !== null && (
            <>
              {" · "}
              <span className={cn("font-mono", Math.abs(s.drift) >= 5 ? "text-bad" : "text-ink-2")}>
                {s.drift >= 0 ? "+" : ""}
                {s.drift.toFixed(1)} pts
              </span>
            </>
          )}
        </p>
      </div>
      <span className="flex items-center gap-1 text-xs text-muted">
        <input
          aria-label={`Target for ${s.sector} (%)`}
          inputMode="decimal"
          placeholder="—"
          value={draft}
          onChange={(e) => onDraft(e.target.value)}
          className="h-8 w-16 rounded-control border border-rule bg-paper-3 px-2 text-right font-mono text-sm text-ink placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        />
        <span aria-hidden>%</span>
      </span>
    </li>
  )
}
