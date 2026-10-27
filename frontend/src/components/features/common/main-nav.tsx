"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { cn } from "@/lib/utils"

const LINKS = [
  { href: "/", label: "Watchlist", match: (path: string) => path === "/" || path.startsWith("/symbols") },
  { href: "/runs", label: "Runs", match: (path: string) => path.startsWith("/runs") },
  { href: "/agents", label: "Agents", match: (path: string) => path.startsWith("/agents") },
  { href: "/usage", label: "Tokens & cost", match: (path: string) => path.startsWith("/usage") },
] as const

/** Top bar: the wordmark and the four destinations, the current one marked. */
export function MainNav() {
  const pathname = usePathname() ?? "/"
  return (
    <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center gap-1 overflow-x-auto px-4 py-2 text-sm">
      <Link href="/" className="mr-4 shrink-0 rounded-control px-1 py-1.5 font-medium whitespace-nowrap text-ink">
        agentsForStocks
      </Link>
      {LINKS.map(({ href, label, match }) => {
        const current = match(pathname)
        return (
          <Link
            key={href}
            href={href}
            aria-current={current ? "page" : undefined}
            className={cn(
              "shrink-0 rounded-control px-3 py-1.5 whitespace-nowrap transition-colors duration-[var(--dur-micro)]",
              current
                ? "bg-paper-2 text-ink shadow-[inset_0_-2px_0_var(--color-accent)]"
                : "text-muted hover:bg-paper-2 hover:text-ink",
            )}
          >
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
