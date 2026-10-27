import type { Metadata } from "next"
import { Atkinson_Hyperlegible_Mono, Host_Grotesk } from "next/font/google"
import type { ReactNode } from "react"

import { MainNav } from "@/components/features/common/main-nav"

import "./globals.css"
import { Providers } from "./providers"

// Console theme: Host Grotesk for what a person reads, Atkinson Hyperlegible Mono for what was measured
const hostGrotesk = Host_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-host-grotesk",
  display: "swap",
})
const atkinsonMono = Atkinson_Hyperlegible_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-atkinson-mono",
  display: "swap",
  // next/font has no fallback metrics for this face; the mono fallback is close enough
  adjustFontFallback: false,
})

export const metadata: Metadata = {
  title: "agentsForStocks",
  description: "Multi-agent stock analysis dashboard",
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`dark ${hostGrotesk.variable} ${atkinsonMono.variable}`}>
      <body>
        <Providers>
          <header className="border-b border-rule bg-paper-3">
            <MainNav />
          </header>
          <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  )
}
