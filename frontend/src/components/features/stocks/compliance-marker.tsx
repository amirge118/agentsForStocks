import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { ComplianceFinding, ComplianceStatus } from "@/types/api"

export const RULE_LABEL: Record<string, string> = {
  promissory_language: "Promissory language",
  exaggerated_claim: "Exaggerated claim",
  missing_risk_discussion: "No risk discussed",
}

/** "Promissory language “guaranteed”" — the rule, plus the phrase when there is one. */
export function findingLabel(finding: ComplianceFinding): string {
  const rule = RULE_LABEL[finding.rule] ?? finding.rule
  return finding.phrase ? `${rule} “${finding.phrase}”` : rule
}

/**
 * Short marker for text the compliance review flagged or replaced, with the
 * findings in a tooltip (on hover and keyboard focus).
 * Renders nothing when the review passed or its outcome is unknown.
 */
export function ComplianceMarker({
  status,
  findings = [],
}: {
  status: ComplianceStatus | null | undefined
  findings?: readonly ComplianceFinding[]
}) {
  if (status !== "flag" && status !== "fail") return null

  const badge = (
    <Badge
      variant={status === "fail" ? "loss" : "outline"}
      aria-label={status === "fail" ? "Compliance: original reasoning replaced" : "Compliance: flagged"}
      tabIndex={findings.length > 0 ? 0 : undefined}
      className={findings.length > 0 ? "cursor-help" : undefined}
    >
      {status === "fail" ? "Replaced" : "Flagged"}
    </Badge>
  )
  if (findings.length === 0) return badge

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent>
          <ul className="space-y-0.5">
            {findings.map((f, i) => (
              <li key={`${f.rule}-${i}`}>{findingLabel(f)}</li>
            ))}
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
