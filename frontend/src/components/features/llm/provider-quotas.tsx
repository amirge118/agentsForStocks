"use client"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { Badge } from "@/components/ui/badge"
import { formatTokens } from "@/lib/format"
import { useLLMProviders } from "@/lib/hooks/queries"
import type { LLMProvider } from "@/types/api"

/** The configured model providers, in fallback-chain order, with today's use of each free tier. */
export function ProviderQuotas() {
  const { data, isPending, isError, error } = useLLMProviders()

  if (isPending) return <Loading label="Loading providers" className="h-28" />
  if (isError) {
    return <LoadError what="providers" error={error} className="p-0" />
  }
  if (data.length === 0) return <Empty className="p-0">No model provider configured.</Empty>

  // Chain steps first, in order; providers outside the chain after them
  const sorted = [...data].sort(
    (a, b) => (a.chain_position ?? Infinity) - (b.chain_position ?? Infinity),
  )
  return (
    <ul className="grid gap-4 md:grid-cols-3" aria-label="Model providers">
      {sorted.map((p) => (
        <ProviderCard key={p.name} provider={p} />
      ))}
    </ul>
  )
}

function ProviderCard({ provider: p }: { provider: LLMProvider }) {
  return (
    <li className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-sm" aria-label={p.name}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{p.name}</span>
        <Badge variant={p.chain_position !== null ? "default" : "outline"}>
          {p.chain_position !== null ? `chain #${p.chain_position}` : "not in chain"}
        </Badge>
      </div>
      <p className="mt-1 truncate font-mono text-xs text-zinc-400">{p.model}</p>
      <dl className="mt-3 space-y-2 tabular-nums">
        <Usage label="Requests today" used={p.day_requests} limit={p.rpd} />
        <Usage label="Tokens today" used={p.day_tokens} limit={p.tpd} />
      </dl>
    </li>
  )
}

function Usage({ label, used, limit }: { label: string; used: number; limit: number | null }) {
  const share = limit ? Math.min(100, (100 * used) / limit) : null
  return (
    <div>
      <div className="flex justify-between text-xs">
        <dt className="text-zinc-400">{label}</dt>
        <dd className="font-mono">
          {formatTokens(used)}
          {limit ? ` / ${formatTokens(limit)}` : ""}
        </dd>
      </div>
      {share !== null && (
        <div
          className="mt-1 h-1.5 rounded-sm bg-zinc-800"
          role="meter"
          aria-label={`${label} of the daily limit`}
          aria-valuenow={Math.round(share)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className={`h-full rounded-sm ${share >= 90 ? "bg-red-400" : "bg-green-400"}`}
            style={{ width: `${share}%` }}
          />
        </div>
      )}
    </div>
  )
}
