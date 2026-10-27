"use client"

import { Component, type ReactNode } from "react"

interface Props {
  label: string
  children: ReactNode
}

interface State {
  failed: boolean
}

/** Agent widgets fail independently — one broken panel must not blank the page. */
export class AgentErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <div role="alert" className="rounded-card border border-rule bg-paper-2 p-6 text-sm text-bad">
          {this.props.label} could not be displayed.
        </div>
      )
    }
    return this.props.children
  }
}
