import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { AgentRunsTable } from "@/components/features/agents/agent-runs-table"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function RunsPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent runs</CardTitle>
        <CardDescription>Every agent execution, newest first (refreshes every 10s)</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <AgentErrorBoundary label="Agent runs">
          <AgentRunsTable filters={{ limit: 200 }} />
        </AgentErrorBoundary>
      </CardContent>
    </Card>
  )
}
