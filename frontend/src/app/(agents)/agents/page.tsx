import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { AgentsTable } from "@/components/features/agents/agents-table"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function AgentsPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents</CardTitle>
        <CardDescription>
          Execution order, recommendation weight, and the model and skills each agent uses
          (change them with AGENT_PROFILES). Between runs an agent&apos;s stored result is used, with no
          data fetched and no model call (change how often with AGENT_REFRESH).
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <AgentErrorBoundary label="Agents">
          <AgentsTable />
        </AgentErrorBoundary>
      </CardContent>
    </Card>
  )
}
