import type { ReactNode } from "react"

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/** One figure with its label; the label explains itself on hover or focus. */
export function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: ReactNode
  hint: string
  tone?: "ok" | "bad"
}) {
  return (
    <div className="min-w-0">
      <dt>
        <TooltipProvider delayDuration={150}>
          <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="cursor-help rounded-chip text-left text-xs text-muted underline decoration-rule-2 decoration-dotted underline-offset-4"
            >
              {label}
            </button>
          </TooltipTrigger>
          <TooltipContent>{hint}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </dt>
      <dd className={cn("mt-0.5 font-mono text-sm", tone === "ok" && "text-ok", tone === "bad" && "text-bad")}>
        {value}
      </dd>
    </div>
  )
}

/** A value in [-1, +1] as a bar growing from the centre. */
export function SignedBar({ label, value }: { label: string; value: number }) {
  const clamped = Math.max(-1, Math.min(1, value))
  const width = `${Math.abs(clamped) * 50}%`
  return (
    <div className="grid grid-cols-[6.5rem_1fr_3rem] items-center gap-2 text-xs">
      <span className="truncate text-muted capitalize">{label.replace(/_/g, " ")}</span>
      <div className="relative h-1.5 rounded-full bg-paper-3" aria-hidden>
        <div className="absolute inset-y-0 left-1/2 w-px bg-rule-2" />
        <div
          className={cn("absolute inset-y-0 rounded-full", clamped >= 0 ? "left-1/2 bg-ok" : "right-1/2 bg-bad")}
          style={{ width }}
        />
      </div>
      <span className={cn("text-right font-mono", clamped >= 0 ? "text-ok" : "text-bad")}>
        {clamped >= 0 ? "+" : ""}
        {clamped.toFixed(2)}
      </span>
    </div>
  )
}
