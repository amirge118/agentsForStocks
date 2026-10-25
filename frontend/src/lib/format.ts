/** Finance formatting rules from CLAUDE.md — keep every number on screen consistent. */

export function formatCurrency(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" })
}

/** Percentage with an explicit sign: 12.3 → "+12.30%". */
export function formatPercent(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`
}

/** Signed score without a unit: 42 → "+42.0". */
export function formatScore(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}`
}

/** 0-100 confidence → "72%". */
export function formatConfidence(n: number): string {
  return `${Math.round(n)}%`
}

export function formatDate(iso: string): string {
  // Market dates are plain YYYY-MM-DD — format in UTC so the day never shifts
  return new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** Text + background classes for a gain / loss / flat value. */
export function toneClasses(n: number): string {
  if (n > 0) return "text-green-400 bg-green-400/10"
  if (n < 0) return "text-red-400 bg-red-400/10"
  return "text-zinc-400 bg-zinc-800"
}
