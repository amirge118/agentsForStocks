import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { HoldingsTable } from "@/components/features/portfolio/holdings-table"
import { PerformanceChart } from "@/components/features/portfolio/performance-chart"
import { PortfolioSummary } from "@/components/features/portfolio/portfolio-summary"
import { TransactionForm } from "@/components/features/portfolio/transaction-form"
import { TransactionsTable } from "@/components/features/portfolio/transactions-table"
import { WeeklyMovers } from "@/components/features/portfolio/weekly-movers"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function PortfolioPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-xl">Portfolio</h1>
        <p className="text-sm text-muted">
          What you hold at today&apos;s prices, next to what the agents say. Prices refresh every minute;
          recommendations once a day, after the close.
        </p>
      </div>
      <AgentErrorBoundary label="The portfolio summary">
        <PortfolioSummary />
      </AgentErrorBoundary>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] [&>*]:min-w-0">
        <Card>
          <CardHeader>
            <CardTitle>Return against the market</CardTitle>
            <CardDescription>How the money did since the first entry, next to the market index.</CardDescription>
          </CardHeader>
          <CardContent>
            <AgentErrorBoundary label="The performance chart">
              <PerformanceChart />
            </AgentErrorBoundary>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>This week&apos;s movers</CardTitle>
            <CardDescription>The biggest moves among the holdings, with the agents&apos; current call.</CardDescription>
          </CardHeader>
          <CardContent>
            <AgentErrorBoundary label="This week's movers">
              <WeeklyMovers />
            </AgentErrorBoundary>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Holdings</CardTitle>
          <CardDescription>Largest first. P/L is against what the shares cost, fees included.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <AgentErrorBoundary label="The holdings">
            <HoldingsTable />
          </AgentErrorBoundary>
        </CardContent>
      </Card>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] [&>*]:min-w-0">
        <Card>
          <CardHeader>
            <CardTitle>Record a transaction</CardTitle>
            <CardDescription>Cash and holdings are worked out from these entries.</CardDescription>
          </CardHeader>
          <CardContent>
            <TransactionForm />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Transactions</CardTitle>
            <CardDescription>Newest first.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <AgentErrorBoundary label="The transactions">
              <TransactionsTable />
            </AgentErrorBoundary>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
