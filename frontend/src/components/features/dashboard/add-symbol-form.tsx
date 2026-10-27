"use client"

import { useId, useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { useWatchlistMutations } from "@/lib/hooks/queries"

// Same rule as the backend's validate_symbol: letters, digits and ".", at most 10
const SYMBOL = /^[A-Z0-9.]{1,10}$/

/** Add a ticker to the watchlist; the format is checked here, the duplicate check by the API. */
export function AddSymbolForm() {
  const { add } = useWatchlistMutations()
  const [value, setValue] = useState("")
  const [invalid, setInvalid] = useState(false)
  const inputId = useId()
  const hintId = useId()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const symbol = value.trim().toUpperCase()
    if (!SYMBOL.test(symbol)) {
      setInvalid(true)
      return
    }
    setInvalid(false)
    add.mutate(symbol, { onSuccess: () => setValue("") })
  }

  return (
    <form onSubmit={submit} className="flex items-start gap-2" aria-label="Add a symbol">
      <div className="space-y-1">
        <label htmlFor={inputId} className="sr-only">
          Ticker symbol
        </label>
        <input
          id={inputId}
          value={value}
          onChange={(e) => {
            setValue(e.target.value.toUpperCase())
            if (invalid) setInvalid(false)
          }}
          placeholder="Ticker, e.g. AAPL"
          maxLength={10}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={invalid}
          aria-describedby={invalid ? hintId : undefined}
          className="h-9 w-40 rounded-control border border-rule bg-paper-3 px-3 font-mono text-sm text-ink placeholder:font-sans placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus aria-invalid:border-bad"
        />
        {invalid && (
          <p id={hintId} className="text-xs text-bad">
            Letters, digits and &ldquo;.&rdquo; only, up to 10.
          </p>
        )}
      </div>
      <Button type="submit" variant="outline" disabled={add.isPending}>
        {add.isPending ? "Adding…" : "Add"}
      </Button>
    </form>
  )
}
