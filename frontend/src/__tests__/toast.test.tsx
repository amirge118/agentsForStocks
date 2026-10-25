import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { Toaster } from "@/components/ui/toaster"
import { toast } from "@/lib/hooks/use-toast"

describe("toast", () => {
  afterEach(() => jest.useRealTimers())

  it("shows one toast at a time and removes it after dismissal", async () => {
    jest.useFakeTimers()
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
    render(<Toaster />)

    act(() => {
      toast({ title: "First" })
      toast({ title: "Second", variant: "destructive" })
    })
    expect(screen.queryByText("First")).not.toBeInTheDocument()
    expect(screen.getByText("Second")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Close" }))
    act(() => {
      jest.advanceTimersByTime(5_000)
    })
    expect(screen.queryByText("Second")).not.toBeInTheDocument()
  })

  it("can be dismissed programmatically", () => {
    jest.useFakeTimers()
    render(<Toaster />)
    let handle: { dismiss: () => void } | undefined
    act(() => {
      handle = toast({ title: "Bye" })
    })
    act(() => {
      handle?.dismiss()
      jest.advanceTimersByTime(5_000)
    })
    expect(screen.queryByText("Bye")).not.toBeInTheDocument()
  })
})
