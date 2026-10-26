import { cn } from "@/lib/utils"

const TONE: Record<string, string> = {
  bullish: "text-ok",
  bearish: "text-bad",
}

export function SignalText({ signal }: { signal: string }) {
  return <span className={cn("capitalize", TONE[signal] ?? "text-muted")}>{signal}</span>
}
