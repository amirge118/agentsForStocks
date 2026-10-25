"use client"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { formatCost, formatDateTime, formatTokens } from "@/lib/format"
import { useRunLLMCalls } from "@/lib/hooks/queries"
import type { LLMCall } from "@/types/api"

/** Every request one agent run sent to the model — what was asked, and what came back. */
export function LLMCallsList({ runId }: { runId: string }) {
  const { data, isPending, isError, error } = useRunLLMCalls(runId)

  if (isPending) {
    return <Skeleton className="h-48 w-full" aria-label="Loading LLM calls" />
  }
  if (isError) {
    return (
      <p role="alert" className="p-6 text-sm text-red-400">
        Could not load LLM calls: {error.message}
      </p>
    )
  }
  if (data.length === 0) {
    return <p className="p-6 text-sm text-zinc-400">This run made no LLM calls.</p>
  }
  return (
    <ol className="space-y-4" aria-label="LLM calls">
      {data.map((call) => (
        <CallCard key={call.call_id} call={call} />
      ))}
    </ol>
  )
}

function CallCard({ call }: { call: LLMCall }) {
  return (
    <li className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={call.status === "ok" ? "gain" : "loss"}>{call.status}</Badge>
        <span className="font-mono">{call.model}</span>
        <span className="text-zinc-400">
          {call.prompt_name ?? "—"}@{call.prompt_version}
        </span>
        <span className="text-zinc-400">{formatDateTime(call.created_at)}</span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 tabular-nums md:grid-cols-5">
        <Field label="Input" value={formatTokens(call.input_tokens + call.cache_read_tokens + call.cache_write_tokens)} />
        <Field label="Output" value={formatTokens(call.output_tokens)} />
        <Field label="Cache read" value={formatTokens(call.cache_read_tokens)} />
        <Field label="Cost" value={formatCost(call.cost_usd)} />
        <Field label="Latency" value={`${call.latency_ms} ms`} />
      </dl>
      {call.error && <p className="mt-2 text-red-400">{call.error}</p>}
      <Text label="System prompt" text={call.system_prompt} />
      <Text label="Prompt" text={call.prompt} />
      <Text label="Response" text={call.response} />
    </li>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-zinc-400">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  )
}

function Text({ label, text }: { label: string; text: string | null }) {
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-zinc-400 hover:text-zinc-50">{label}</summary>
      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-zinc-950 p-3 font-mono text-xs">
        {text ?? "Not captured (LLM_CAPTURE_CONTENT=false)"}
      </pre>
    </details>
  )
}
