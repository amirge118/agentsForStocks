import { Badge } from "@/components/ui/badge"
import type { ComplianceStatus } from "@/types/api"

/**
 * Short marker for text the compliance review flagged or replaced.
 * Renders nothing when the review passed or its outcome is unknown.
 */
export function ComplianceMarker({ status }: { status: ComplianceStatus | null | undefined }) {
  if (status !== "flag" && status !== "fail") return null
  return (
    <Badge
      variant={status === "fail" ? "loss" : "outline"}
      aria-label={status === "fail" ? "Compliance: original reasoning replaced" : "Compliance: flagged"}
    >
      {status === "fail" ? "Replaced" : "Flagged"}
    </Badge>
  )
}
