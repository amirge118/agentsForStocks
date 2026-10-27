import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { AgentRunsTable } from "@/components/features/agents/agent-runs-table"
import { RunPipelineButton } from "@/components/features/dashboard/run-pipeline-button"
import { AgentPanels } from "@/components/features/stocks/agent-panels"
import { PriceChart } from "@/components/features/stocks/price-chart"
import { RecommendationCard } from "@/components/features/stocks/recommendation-card"
import { ScoreHistoryChart } from "@/components/features/stocks/score-history-chart"
import { TrackRecordCard } from "@/components/features/stocks/track-record-card"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Suspense } from "react"

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
        <CardContent className="p-6">
          <AgentErrorBoundary label="The price chart">
            <Suspense>
              <PriceChart symbol={symbol} />
            </Suspense>
          </AgentErrorBoundary>
        </CardContent>
      </Card>
      <AgentErrorBoundary label="The agent panels">
        <AgentPanels symbol={symbol} />
      </AgentErrorBoundary>
      <Card>
        <CardContent className="p-6">
          <AgentErrorBoundary label="The score history">
            <ScoreHistoryChart symbol={symbol} />
          </AgentErrorBoundary>
        </CardContent>
      </Card>
      <AgentErrorBoundary label="The track record">
        <TrackRecordCard symbol={symbol} />
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
