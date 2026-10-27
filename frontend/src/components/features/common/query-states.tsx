import type { ReactNode } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/** The loading, error and empty states every data component shows the same way. */

export function Loading({ label, className = "h-48" }: { label: string; className?: string }) {
  return <Skeleton className={cn("w-full", className)} aria-label={label} />
}

export function LoadError({
  what,
  error,
  className,
}: {
  what: string
  error: Error
  className?: string
}) {
  return (
    <p role="alert" className={cn("p-6 text-sm text-bad", className)}>
      Could not load {what}: {error.message}
    </p>
  )
}

export function Empty({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("p-6 text-sm text-muted", className)}>{children}</p>
}
