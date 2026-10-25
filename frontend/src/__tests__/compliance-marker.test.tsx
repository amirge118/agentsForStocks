import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ComplianceMarker, findingLabel } from "@/components/features/stocks/compliance-marker"

const promissory = { rule: "promissory_language", severity: "fail" as const, phrase: "guaranteed" }
const noRisk = { rule: "missing_risk_discussion", severity: "flag" as const, phrase: "" }

describe("ComplianceMarker", () => {
  it("renders nothing when the review passed or is unknown", () => {
    const { container, rerender } = render(<ComplianceMarker status="pass" findings={[promissory]} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<ComplianceMarker status={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("shows the findings in a tooltip on keyboard focus", async () => {
    render(<ComplianceMarker status="fail" findings={[promissory, noRisk]} />)

    await userEvent.tab()
    const badge = screen.getByLabelText("Compliance: original reasoning replaced")
    expect(badge).toHaveFocus()

    const tooltip = await screen.findByRole("tooltip")
    expect(tooltip).toHaveTextContent("Promissory language “guaranteed”")
    expect(tooltip).toHaveTextContent("No risk discussed")
  })

  it("has no tooltip and is not focusable without findings", async () => {
    render(<ComplianceMarker status="flag" />)

    await userEvent.tab()
    expect(screen.getByLabelText("Compliance: flagged")).not.toHaveFocus()
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()
  })

  it("labels unknown rules by their id", () => {
    expect(findingLabel({ rule: "new_rule", severity: "flag", phrase: "" })).toBe("new_rule")
  })
})
