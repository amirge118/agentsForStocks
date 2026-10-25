import "@testing-library/jest-dom"

// jsdom lacks the Pointer Capture API that Radix primitives call on click
// (skipped in suites that run in the node environment)
if (typeof Element !== "undefined" && !Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.setPointerCapture = () => undefined
  Element.prototype.releasePointerCapture = () => undefined
}
