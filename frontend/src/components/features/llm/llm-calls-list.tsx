"use client"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { Badge } from "@/components/ui/badge"
import { formatCost, formatDateTime, formatTokens } from "@/lib/format"
import { useRunLLMCalls } from "@/lib/hooks/queries"
import type { LLMCall } from "@/types/api"

/** Every request one agent run sent to the model — what was asked, and what came back. */
export function LLMCallsList({ runId }: { runId: string }) {
  const { data, isPending, isError, error } = useRunLLMCalls(runId)

  if (isPending) {
    return <Loading label="Loading LLM calls" />
  }
  if (isError) {
    return <LoadError what="LLM calls" error={error} />
  }
  if (data.length === 0) {
    return <p className="p-6 text-sm text-muted">This run made no LLM calls.</p>
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
    <li className="rounded-card border border-rule bg-paper-2 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={call.status === "ok" ? "gain" : "loss"}>{call.status}</Badge>
        <span className="font-mono">{call.model}</span>
        {call.provider && <span className="text-muted">via {call.provider}</span>}
        <span className="text-muted">
          {call.prompt_name ?? "—"}@{call.prompt_version}
        </span>
        <span className="text-muted">{formatDateTime(call.created_at)}</span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 tabular-nums md:grid-cols-5">
        <Field label="Input" value={formatTokens(call.input_tokens + call.cache_read_tokens + call.cache_write_tokens)} />
        <Field label="Output" value={formatTokens(call.output_tokens)} />
        <Field label="Cache read" value={formatTokens(call.cache_read_tokens)} />
        <Field label="Cost" value={formatCost(call.cost_usd)} />
        <Field label="Latency" value={`${call.latency_ms} ms`} />
      </dl>
      {call.error && <p className="mt-2 text-bad">{call.error}</p>}
      <Text label="System prompt" text={call.system_prompt} />
      <Text label="Prompt" text={call.prompt} />
      <Text label="Response" text={call.response} />
    </li>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  )
}

function Text({ label, text }: { label: string; text: string | null }) {
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-muted hover:text-ink">{label}</summary>
      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-control border border-rule bg-paper-3 p-3 font-mono text-xs">
        {text ?? "Not captured (LLM_CAPTURE_CONTENT=false)"}
      </pre>
    </details>
  )
}
