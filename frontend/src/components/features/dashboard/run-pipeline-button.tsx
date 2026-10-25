"use client"

import { Button } from "@/components/ui/button"
import { useStartPipelineRun } from "@/lib/hooks/queries"

export function RunPipelineButton({ symbols }: { symbols?: string[] }) {
  const { mutate, isPending } = useStartPipelineRun()
  return (
    <Button
      onClick={() => mutate({ symbols: symbols ?? null, agents: null, force: false })}
      disabled={isPending}
    >
      {isPending ? "Starting…" : "Run analysis"}
    </Button>
  )
}
