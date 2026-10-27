import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { TrackRecordTable } from "@/components/features/outcomes/track-record-table"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function TrackRecordPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Track record</CardTitle>
        <CardDescription>
          How each agent&apos;s calls turned out against the benchmark. A bullish call is right
          when the stock beat it, bearish when it lagged, neutral when it stayed close.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        <AgentErrorBoundary label="The track record">
          <TrackRecordTable />
        </AgentErrorBoundary>
      </CardContent>
    </Card>
  )
}
