"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { cn } from "@/lib/utils"

/** The four views of the agents, one tab each; the main bar shows them as one "Agents". */
export const AGENT_TABS = [
  { href: "/agents", label: "Agents" },
  { href: "/runs", label: "Runs" },
  { href: "/track-record", label: "Track record" },
  { href: "/usage", label: "Tokens & cost" },
] as const

export function isAgentsPath(path: string): boolean {
  return AGENT_TABS.some((t) => path === t.href || path.startsWith(`${t.href}/`))
}

export function AgentsTabs() {
  const pathname = usePathname() ?? ""
  return (
    <nav aria-label="Agents" className="-mt-2 mb-6 flex gap-1 overflow-x-auto border-b border-rule text-sm">
      {AGENT_TABS.map(({ href, label }) => {
        const current = pathname === href || pathname.startsWith(`${href}/`)
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={cn(
              "-mb-px shrink-0 border-b-2 px-3 py-2 whitespace-nowrap transition-colors duration-[var(--dur-micro)]",
              current ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
