import type { Metadata } from "next"
import Link from "next/link"
import type { ReactNode } from "react"

import "./globals.css"
import { Providers } from "./providers"

export const metadata: Metadata = {
  title: "agentsForStocks",
  description: "Multi-agent stock analysis dashboard",
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>
          <header className="border-b border-zinc-800">
            <nav className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3 text-sm">
              <Link href="/" className="font-semibold">
                agentsForStocks
              </Link>
              <Link href="/" className="text-zinc-400 hover:text-zinc-50">
                Watchlist
              </Link>
              <Link href="/runs" className="text-zinc-400 hover:text-zinc-50">
                Runs
              </Link>
              <Link href="/agents" className="text-zinc-400 hover:text-zinc-50">
                Agents
              </Link>
              <Link href="/usage" className="text-zinc-400 hover:text-zinc-50">
                Tokens &amp; cost
              </Link>
            </nav>
          </header>
          <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  )
}
