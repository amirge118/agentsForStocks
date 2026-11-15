"use client"

import { Empty, LoadError, Loading } from "@/components/features/common/query-states"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatCurrency, formatDate, formatSignedCurrency } from "@/lib/format"
import { usePortfolioMutations, useTransactions } from "@/lib/hooks/queries"
import { cn } from "@/lib/utils"
import type { Transaction } from "@/types/api"

import { KIND_LABELS } from "./transaction-form"

/** What an entry did to the cash; null when it moved none (a transfer in). */
export function cashEffect(t: Transaction): number | null {
  const gross = (t.shares ?? 0) * (t.price ?? 0)
  switch (t.kind) {
    case "DEPOSIT":
    case "DIVIDEND":
      return t.amount
    case "WITHDRAW":
      return t.amount === null ? null : -t.amount
    case "BUY":
      return -(gross + t.fee)
    case "SELL":
      return gross - t.fee
    default:
      return null
  }
}

/** The ledger, newest first. Removing an entry a later one depends on is refused by the API. */
export function TransactionsTable() {
  const { data, isPending, isError, error } = useTransactions()
  const { remove } = usePortfolioMutations()

  if (isPending) return <Loading label="Loading transactions" className="h-32" />
  if (isError) return <LoadError what="the transactions" error={error} />
  if (data.length === 0) return <Empty>No transactions yet.</Empty>

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="hidden sm:table-cell">Date</TableHead>
          <TableHead>Kind</TableHead>
          <TableHead className="hidden sm:table-cell">Detail</TableHead>
          <TableHead className="text-right">Cash</TableHead>
          <TableHead className="text-right">
            <span className="sr-only">Delete</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((t) => {
          const cash = cashEffect(t)
          return (
            <TableRow key={t.id}>
              <TableCell className="hidden whitespace-nowrap text-ink-2 sm:table-cell">
                {formatDate(t.trade_date)}
              </TableCell>
              <TableCell>
                {KIND_LABELS[t.kind]}
                {t.symbol && <span className="ml-1.5 font-mono font-medium">{t.symbol}</span>}
                {/* On a phone the Date column is hidden, so Delete still fits */}
                <span className="block text-xs text-muted sm:hidden">{formatDate(t.trade_date)}</span>
              </TableCell>
              <TableCell className="hidden text-xs text-muted sm:table-cell">
                {t.shares !== null && t.price !== null && (
                  <span className="font-mono">
                    {t.shares.toLocaleString("en-US", { maximumFractionDigits: 6 })} × {formatCurrency(t.price)}
                    {t.fee > 0 && ` + ${formatCurrency(t.fee)} fee`}
                  </span>
                )}
                {t.note && <span className="block">{t.note}</span>}
              </TableCell>
              <TableCell
                className={cn(
                  "text-right font-mono",
                  cash === null ? "text-muted" : cash > 0 ? "text-ok" : cash < 0 ? "text-bad" : "",
                )}
              >
                {cash === null ? "—" : formatSignedCurrency(cash)}
              </TableCell>
              <TableCell className="text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Delete the ${KIND_LABELS[t.kind].toLowerCase()} of ${formatDate(t.trade_date)}`}
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm("Delete this transaction? Cash and holdings are recalculated.")) {
                      remove.mutate(t.id)
                    }
                  }}
                >
                  Delete
                </Button>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
