import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

/**
 * Marker for a result a person should check before trusting it — the model was
 * unavailable and a rule-based fallback stood in, or too few analysts reported.
 * The reasons, when known, are in a tooltip. Renders nothing when there are none.
 */
export function ReviewMarker({ reasons }: { reasons: readonly string[] | boolean | undefined }) {
  const list = Array.isArray(reasons) ? reasons : []
  if (!(reasons === true || list.length > 0)) return null

  const badge = (
    <Badge
      variant="outline"
      aria-label={list.length > 0 ? `Needs review: ${list.join("; ")}` : "Needs review: the model was unavailable"}
      tabIndex={list.length > 0 ? 0 : undefined}
      className={list.length > 0 ? "cursor-help whitespace-nowrap" : "whitespace-nowrap"}
    >
      Needs review
    </Badge>
  )
  if (list.length === 0) return badge

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent>
          <ul className="space-y-0.5">
            {list.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
