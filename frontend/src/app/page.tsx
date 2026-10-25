import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { RunPipelineButton } from "@/components/features/dashboard/run-pipeline-button"
import { WatchlistTable } from "@/components/features/dashboard/watchlist-table"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function DashboardPage() {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="space-y-1.5">
          <CardTitle>Watchlist</CardTitle>
          <CardDescription>Latest recommendation per symbol from the analyst agents</CardDescription>
        </div>
        <RunPipelineButton />
      </CardHeader>
      <CardContent className="p-0">
        <AgentErrorBoundary label="The watchlist">
          <WatchlistTable />
        </AgentErrorBoundary>
      </CardContent>
    </Card>
  )
}
