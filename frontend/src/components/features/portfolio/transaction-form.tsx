"use client"

import { useId, useState, type FormEvent, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { usePortfolioMutations } from "@/lib/hooks/queries"
import type { TransactionIn, TransactionKind } from "@/types/api"

export const KIND_LABELS: Record<TransactionKind, string> = {
  DEPOSIT: "Deposit",
  WITHDRAW: "Withdraw",
  BUY: "Buy",
  SELL: "Sell",
  DIVIDEND: "Dividend",
  TRANSFER_IN: "Transfer in",
}

const WITH_SHARES: TransactionKind[] = ["BUY", "SELL", "TRANSFER_IN"]
const WITH_SYMBOL: TransactionKind[] = ["BUY", "SELL", "TRANSFER_IN", "DIVIDEND"]
const WITH_FEE: TransactionKind[] = ["BUY", "SELL"]
// Same rules as the API: a ticker, and a positive number with up to 6 decimals
const SYMBOL = /^[A-Z0-9.]{1,10}$/
const NUMBER = /^\d+(\.\d{1,6})?$/

const HINTS: Record<TransactionKind, string> = {
  DEPOSIT: "Cash into the portfolio.",
  WITHDRAW: "Cash out of the portfolio.",
  BUY: "Spends cash: shares × price + fee.",
  SELL: "Adds cash and books the P/L against the average cost.",
  DIVIDEND: "Cash paid by a holding.",
  TRANSFER_IN: "Shares you already hold, at what they cost you. Spends no cash.",
}

interface Fields {
  symbol: string
  shares: string
  price: string
  fee: string
  amount: string
  note: string
}

const EMPTY: Fields = { symbol: "", shares: "", price: "", fee: "", amount: "", note: "" }

/** Today in the browser's calendar, as YYYY-MM-DD (the API refuses a future date). */
function today(): string {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

/**
 * One form for every kind of ledger entry; it shows only the fields the kind takes.
 * Formats are checked here, the ledger's rules (enough cash, enough shares) by the API,
 * whose reason is shown under the form.
 */
export function TransactionForm() {
  const { add } = usePortfolioMutations()
  const [kind, setKind] = useState<TransactionKind>("DEPOSIT")
  const [date, setDate] = useState(today)
  const [fields, setFields] = useState<Fields>(EMPTY)
  const [problem, setProblem] = useState<string | null>(null)
  const id = useId()
  const errorId = `${id}-error`

  const set = (name: keyof Fields) => (value: string) => {
    setFields((f) => ({ ...f, [name]: name === "symbol" ? value.toUpperCase() : value }))
    setProblem(null)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const invalid = check(kind, fields)
    if (invalid) {
      setProblem(invalid)
      return
    }
    const body: TransactionIn = {
      trade_date: date,
      kind,
      symbol: WITH_SYMBOL.includes(kind) ? fields.symbol.trim() : null,
      // Strings, not numbers: the API reads them as exact decimals
      shares: WITH_SHARES.includes(kind) ? fields.shares : null,
      price: WITH_SHARES.includes(kind) ? fields.price : null,
      fee: WITH_FEE.includes(kind) && fields.fee ? fields.fee : "0",
      amount: WITH_SHARES.includes(kind) ? null : fields.amount,
      note: fields.note.trim() || null,
    }
    add.mutate(body, {
      onSuccess: () => setFields(EMPTY),
      onError: (error) => setProblem(error.message),
    })
  }

  return (
    <form onSubmit={submit} aria-label="Record a transaction" aria-describedby={problem ? errorId : undefined} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Kind" id={`${id}-kind`}>
          <select
            id={`${id}-kind`}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as TransactionKind)
              setProblem(null)
            }}
            className={INPUT}
          >
            {Object.entries(KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Date" id={`${id}-date`}>
          <input id={`${id}-date`} type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} className={INPUT} required />
        </Field>
        {WITH_SYMBOL.includes(kind) && (
          <Field label="Symbol" id={`${id}-symbol`}>
            <input id={`${id}-symbol`} value={fields.symbol} onChange={(e) => set("symbol")(e.target.value)} placeholder="e.g. MSFT" maxLength={10} autoComplete="off" spellCheck={false} className={`${INPUT} font-mono`} />
          </Field>
        )}
        {WITH_SHARES.includes(kind) ? (
          <>
            <Field label="Shares" id={`${id}-shares`}>
              <input id={`${id}-shares`} inputMode="decimal" value={fields.shares} onChange={(e) => set("shares")(e.target.value)} className={`${INPUT} font-mono`} />
            </Field>
            <Field label={kind === "TRANSFER_IN" ? "Cost per share" : "Price per share"} id={`${id}-price`}>
              <input id={`${id}-price`} inputMode="decimal" value={fields.price} onChange={(e) => set("price")(e.target.value)} className={`${INPUT} font-mono`} />
            </Field>
            {WITH_FEE.includes(kind) && (
              <Field label="Fee" id={`${id}-fee`}>
                <input id={`${id}-fee`} inputMode="decimal" value={fields.fee} onChange={(e) => set("fee")(e.target.value)} placeholder="0" className={`${INPUT} font-mono`} />
              </Field>
            )}
          </>
        ) : (
          <Field label="Amount ($)" id={`${id}-amount`}>
            <input id={`${id}-amount`} inputMode="decimal" value={fields.amount} onChange={(e) => set("amount")(e.target.value)} className={`${INPUT} font-mono`} />
          </Field>
        )}
        <Field label="Note (optional)" id={`${id}-note`} wide>
          <input id={`${id}-note`} value={fields.note} onChange={(e) => set("note")(e.target.value)} maxLength={200} className={INPUT} />
        </Field>
      </div>
      <p className="text-xs text-muted">{HINTS[kind]}</p>
      {problem && (
        <p id={errorId} role="alert" className="text-sm text-bad">
          {problem}
        </p>
      )}
      <Button type="submit" disabled={add.isPending}>
        {add.isPending ? "Recording…" : `Record ${KIND_LABELS[kind].toLowerCase()}`}
      </Button>
    </form>
  )
}

function check(kind: TransactionKind, f: Fields): string | null {
  if (WITH_SYMBOL.includes(kind) && !SYMBOL.test(f.symbol.trim())) return "Enter a ticker: letters, digits and “.” only."
  const numbers = WITH_SHARES.includes(kind)
    ? [
        ["Shares", f.shares],
        ["Price", f.price],
        ...(f.fee ? [["Fee", f.fee]] : []),
      ]
    : [["Amount", f.amount]]
  for (const [label, value] of numbers) {
    if (!NUMBER.test(value!.trim())) return `${label}: a number, up to 6 decimals.`
    if (label !== "Fee" && Number(value) <= 0) return `${label} must be above 0.`
  }
  return null
}

const INPUT =
  "h-9 w-full rounded-control border border-rule bg-paper-3 px-3 text-sm text-ink placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"

function Field({ label, id, wide, children }: { label: string; id: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={wide ? "col-span-2 min-w-0 space-y-1" : "min-w-0 space-y-1"}>
      <label htmlFor={id} className="text-xs text-muted">
        {label}
      </label>
      {children}
    </div>
  )
}
