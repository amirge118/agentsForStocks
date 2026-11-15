import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { LLMCallsList } from "@/components/features/llm/llm-calls-list"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const runId = decodeURIComponent((await params).runId)
  return (
    <Card>
      <CardHeader>
        <CardTitle>What was sent to the model</CardTitle>
        <CardDescription className="font-mono">Run {runId}</CardDescription>
      </CardHeader>
      <CardContent>
        <AgentErrorBoundary label="LLM calls">
          <LLMCallsList runId={runId} />
        </AgentErrorBoundary>
      </CardContent>
    </Card>
  )
}
