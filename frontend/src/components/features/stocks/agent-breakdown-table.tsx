import { ComplianceMarker } from "@/components/features/stocks/compliance-marker"
import { SignalText } from "@/components/features/stocks/signal-text"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatConfidence, formatScore, toneClasses } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Contribution } from "@/types/api"

export function AgentBreakdownTable({ breakdown }: { breakdown: readonly Contribution[] }) {
  return (
    <Table aria-label="Agent breakdown">
      <TableHeader>
        <TableRow>
          <TableHead>Analyst</TableHead>
          <TableHead>Signal</TableHead>
          <TableHead className="text-right">Confidence</TableHead>
          <TableHead className="text-right">Weight</TableHead>
          <TableHead className="text-right">Contribution</TableHead>
          <TableHead className="hidden lg:table-cell">Reasoning</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {breakdown.map((c) => (
          <TableRow key={c.agent}>
            <TableCell className="font-medium">{c.agent.replaceAll("_", " ")}</TableCell>
            <TableCell>
              <div className="flex items-center gap-2">
                <SignalText signal={c.signal} />
                <ComplianceMarker status={c.compliance_status} findings={c.compliance_findings} />
              </div>
            </TableCell>
            <TableCell className="text-right font-mono">
              {c.signal === "missing" ? "—" : formatConfidence(c.confidence)}
            </TableCell>
            <TableCell className="text-right font-mono">{c.weight}</TableCell>
            <TableCell className="text-right font-mono">
              <span className={cn("rounded px-1.5 py-0.5", toneClasses(c.contribution))}>
                {formatScore(c.contribution)}
              </span>
            </TableCell>
            <TableCell className="hidden max-w-sm truncate text-zinc-400 lg:table-cell">
              {c.reasoning}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
