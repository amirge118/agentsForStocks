"use client"

import { Button } from "@/components/ui/button"
import { HORIZONS, type Horizon } from "@/types/api"

const LABELS: Record<Horizon, string> = { 5: "1 week", 20: "1 month", 60: "3 months" }

/** Which window a call is judged on: 5, 20 or 60 trading sessions after it. */
export function HorizonPicker({
  value,
  onChange,
}: {
  value: Horizon
  onChange: (horizon: Horizon) => void
}) {
  return (
    <div className="flex flex-wrap gap-2" role="toolbar" aria-label="Horizon">
      {HORIZONS.map((h) => (
        <Button
          key={h}
          size="sm"
          variant={h === value ? "default" : "outline"}
          aria-pressed={h === value}
          onClick={() => onChange(h)}
        >
          {LABELS[h]}
        </Button>
      ))}
    </div>
  )
}
