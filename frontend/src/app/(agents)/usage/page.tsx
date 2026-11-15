import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { ProviderQuotas } from "@/components/features/llm/provider-quotas"
import { UsageTable } from "@/components/features/llm/usage-table"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function UsagePage() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Model providers</CardTitle>
          <CardDescription>
            Calls go to the free tiers first, in chain order, and to Claude last. Use today is
            counted from midnight in each provider&apos;s time zone.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AgentErrorBoundary label="Model providers">
            <ProviderQuotas />
          </AgentErrorBoundary>
        </CardContent>
      </Card>
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
    </div>
  )
}
