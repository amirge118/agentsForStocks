import { Badge } from "@/components/ui/badge"
import type { Compliance } from "@/types/api"

import { RULE_LABEL } from "./compliance-marker"

/** Compliance review status + findings, and the disclaimer every recommendation carries. */
export function ComplianceNotice({
  compliance,
  disclaimer,
}: {
  compliance: Compliance
  disclaimer: string
}) {
  return (
    <div className="space-y-2 border-t border-rule pt-4 text-xs text-muted">
      {compliance.status !== "pass" && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Compliance review">
          <Badge variant={compliance.status === "fail" ? "loss" : "outline"}>
            {compliance.status === "fail"
              ? "Compliance: original reasoning replaced"
              : "Compliance: flagged"}
          </Badge>
          {compliance.findings.map((f, i) => (
            <span key={`${f.rule}-${i}`}>
              {RULE_LABEL[f.rule] ?? f.rule}
              {f.phrase && <span className="font-mono"> “{f.phrase}”</span>}
            </span>
          ))}
        </div>
      )}
      <p>{disclaimer}</p>
    </div>
  )
}
