import { AgentErrorBoundary } from "@/components/features/agents/agent-error-boundary"
import { HoldingsTable } from "@/components/features/portfolio/holdings-table"
import { PortfolioSummary } from "@/components/features/portfolio/portfolio-summary"
import { TransactionForm } from "@/components/features/portfolio/transaction-form"
import { TransactionsTable } from "@/components/features/portfolio/transactions-table"
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
