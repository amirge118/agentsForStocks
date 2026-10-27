import { render, screen } from "@testing-library/react"

import { MainNav } from "@/components/features/common/main-nav"

const usePathname = jest.fn()
jest.mock("next/navigation", () => ({ usePathname: () => usePathname() }))

describe("MainNav", () => {
  it.each([
    ["/", "Watchlist"],
    ["/symbols/AAPL", "Watchlist"],
    ["/runs/p1", "Runs"],
    ["/agents", "Agents"],
    ["/usage", "Tokens & cost"],
  ])("marks %s as %s", (path, current) => {
    usePathname.mockReturnValue(path)
    render(<MainNav />)
    expect(screen.getByRole("link", { name: current })).toHaveAttribute("aria-current", "page")
    const others = screen
      .getAllByRole("link")
      .filter((link) => link.textContent !== current && link.textContent !== "agentsForStocks")
    others.forEach((link) => expect(link).not.toHaveAttribute("aria-current"))
  })

  it("falls back to the watchlist when the path is unknown", () => {
    usePathname.mockReturnValue(null)
    render(<MainNav />)
    expect(screen.getByRole("link", { name: "Watchlist" })).toHaveAttribute("aria-current", "page")
  })
})
