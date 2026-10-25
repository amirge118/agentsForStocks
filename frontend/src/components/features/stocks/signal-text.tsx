import { cn } from "@/lib/utils"

const TONE: Record<string, string> = {
  bullish: "text-green-400",
  bearish: "text-red-400",
}

export function SignalText({ signal }: { signal: string }) {
  return <span className={cn("capitalize", TONE[signal] ?? "text-zinc-400")}>{signal}</span>
}
