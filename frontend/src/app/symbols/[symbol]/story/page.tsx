import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { AnalysisStory } from "@/components/features/stocks/analysis-story"

export default async function StoryPage({ params }: { params: Promise<{ symbol: string }> }) {
  const symbol = decodeURIComponent((await params).symbol).toUpperCase()
  return (
    <AgentErrorBoundary label="The analysis story">
      <AnalysisStory symbol={symbol} />
    </AgentErrorBoundary>
  )
}
