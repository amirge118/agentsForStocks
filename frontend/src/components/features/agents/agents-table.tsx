"use client"

import { LoadError, Loading } from "@/components/features/common/query-states"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useAgents } from "@/lib/hooks/queries"

/** Every agent in execution order, with its weight and how it calls the model. */
export function AgentsTable() {
  const { data, isPending, isError, error } = useAgents()

  if (isPending) {
    return <Loading label="Loading agents" />
  }
  if (isError) {
    return <LoadError what="agents" error={error} />
  }
  return (
    <Table aria-label="Agents">
      <TableHeader>
        <TableRow>
          <TableHead>Agent</TableHead>
          <TableHead className="hidden md:table-cell">What it analyses</TableHead>
          <TableHead className="text-right">Weight</TableHead>
          <TableHead>Model</TableHead>
          <TableHead>Skills</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((agent) => (
          <TableRow key={agent.name}>
            <TableCell className="font-mono">{agent.name}</TableCell>
            <TableCell className="hidden text-zinc-400 md:table-cell">{agent.description}</TableCell>
            <TableCell className="text-right tabular-nums">
              {agent.recommendation_weight || "info"}
            </TableCell>
            <TableCell>
              {agent.profile.use_llm ? (
                <span className="font-mono text-xs">
                  {agent.profile.provider}
                  {agent.profile.model ? ` · ${agent.profile.model}` : ""}
                </span>
              ) : (
                <Badge variant="outline">rule-based</Badge>
              )}
            </TableCell>
            <TableCell className="space-x-1">
              {agent.profile.skills.length === 0 ? (
                <span className="text-zinc-400">—</span>
              ) : (
                agent.profile.skills.map((skill) => (
                  <Badge key={skill} variant="outline">
                    {skill.replaceAll("_", " ")}
                  </Badge>
                ))
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
