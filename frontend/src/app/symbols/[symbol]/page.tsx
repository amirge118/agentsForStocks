import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { AgentRunsTable } from "@/components/features/agents/agent-runs-table"
import { RunPipelineButton } from "@/components/features/dashboard/run-pipeline-button"
import { RecommendationCard } from "@/components/features/stocks/recommendation-card"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default async function SymbolPage({ params }: { params: Promise<{ symbol: string }> }) {
  const symbol = decodeURIComponent((await params).symbol).toUpperCase()
  return (
    <>
      <div className="flex justify-end">
        <RunPipelineButton symbols={[symbol]} />
      </div>
      <AgentErrorBoundary label="The recommendation">
        <RecommendationCard symbol={symbol} />
      </AgentErrorBoundary>
      <Card>
        <CardHeader>
          <CardTitle>Recent agent runs</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <AgentErrorBoundary label="Agent runs">
            <AgentRunsTable filters={{ symbol, limit: 50 }} />
          </AgentErrorBoundary>
        </CardContent>
      </Card>
    </>
  )
}
