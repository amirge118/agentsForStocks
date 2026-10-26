import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-chip border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-rule bg-paper-3 text-ink-2",
        gain: "border-ok/30 bg-ok-soft text-ok",
        loss: "border-bad/30 bg-bad-soft text-bad",
        outline: "border-rule text-muted",
      },
    },
    defaultVariants: { variant: "default" },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
