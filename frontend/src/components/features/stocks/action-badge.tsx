import { Badge } from "@/components/ui/badge"
import type { Action } from "@/types/api"

const VARIANT: Record<Action, "gain" | "loss" | "default"> = {
  BUY: "gain",
  SELL: "loss",
  HOLD: "default",
}

export function ActionBadge({ action }: { action: Action }) {
  return <Badge variant={VARIANT[action]}>{action}</Badge>
}
