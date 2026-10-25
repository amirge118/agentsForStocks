import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { UsageTable } from "@/components/features/llm/usage-table"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function UsagePage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Tokens &amp; cost</CardTitle>
        <CardDescription>
          Every request to the model, from the LLM ledger. Cache reads count as input.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        <AgentErrorBoundary label="LLM usage">
          <UsageTable />
        </AgentErrorBoundary>
      </CardContent>
    </Card>
  )
}
