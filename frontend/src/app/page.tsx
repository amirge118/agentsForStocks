import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { AgentsOnPortfolio } from "@/components/features/portfolio/agents-on-portfolio"
import { HoldingsTable } from "@/components/features/portfolio/holdings-table"
import { PerformanceChart } from "@/components/features/portfolio/performance-chart"
import { PortfolioSummary } from "@/components/features/portfolio/portfolio-summary"
import { RiskSummary } from "@/components/features/portfolio/risk-summary"
import { SectorWeights } from "@/components/features/portfolio/sector-weights"
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
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 [&>*]:min-w-0">
        <Card>
          <CardHeader>
            <CardTitle>Sectors</CardTitle>
            <CardDescription>Share of the portfolio by sector; the line marks your target.</CardDescription>
          </CardHeader>
          <CardContent>
            <AgentErrorBoundary label="The sectors">
              <SectorWeights />
            </AgentErrorBoundary>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Risk</CardTitle>
            <CardDescription>Concentration, market sensitivity and the fall from the high.</CardDescription>
          </CardHeader>
          <CardContent>
            <AgentErrorBoundary label="The risk readings">
              <RiskSummary />
            </AgentErrorBoundary>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>The agents on your portfolio</CardTitle>
            <CardDescription>The share of the money under each call, from the latest daily run.</CardDescription>
          </CardHeader>
          <CardContent>
            <AgentErrorBoundary label="The agents' view">
              <AgentsOnPortfolio />
            </AgentErrorBoundary>
          </CardContent>
        </Card>
      </div>
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
