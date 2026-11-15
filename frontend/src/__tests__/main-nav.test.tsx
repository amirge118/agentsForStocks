import { render, screen, within } from "@testing-library/react"

import { AgentsTabs } from "@/components/features/common/agents-tabs"
import { MainNav } from "@/components/features/common/main-nav"

const usePathname = jest.fn()
jest.mock("next/navigation", () => ({ usePathname: () => usePathname() }))

describe("MainNav", () => {
  it.each([
    ["/", "Portfolio"],
    ["/watchlist", "Watchlist"],
    ["/symbols/AAPL", "Watchlist"],
    ["/agents", "Agents"],
    ["/runs/p1", "Agents"],
    ["/usage", "Agents"],
    ["/track-record", "Agents"],
  ])("marks %s as %s", (path, current) => {
    usePathname.mockReturnValue(path)
    render(<MainNav />)
    expect(screen.getByRole("link", { name: current })).toHaveAttribute("aria-current", "page")
    const others = screen
      .getAllByRole("link")
      .filter((link) => link.textContent !== current && link.textContent !== "agentsForStocks")
    others.forEach((link) => expect(link).not.toHaveAttribute("aria-current"))
  })

  it("falls back to the portfolio, the first page, when the path is unknown", () => {
    usePathname.mockReturnValue(null)
    render(<MainNav />)
    expect(screen.getByRole("link", { name: "Portfolio" })).toHaveAttribute("aria-current", "page")
  })
})

describe("AgentsTabs", () => {
  it.each([
    ["/agents", "Agents"],
    ["/runs", "Runs"],
    ["/runs/p1", "Runs"],
    ["/track-record", "Track record"],
    ["/usage", "Tokens & cost"],
  ])("on %s, marks the %s tab", (path, current) => {
    usePathname.mockReturnValue(path)
    render(<AgentsTabs />)
    const tabs = screen.getByRole("navigation", { name: "Agents" })
    expect(within(tabs).getAllByRole("link")).toHaveLength(4)
    expect(within(tabs).getByRole("link", { name: current })).toHaveAttribute("aria-current", "page")
  })
})
