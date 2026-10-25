import "@testing-library/jest-dom"

// jsdom lacks the Pointer Capture API that Radix primitives call on click
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.setPointerCapture = () => undefined
  Element.prototype.releasePointerCapture = () => undefined
}
