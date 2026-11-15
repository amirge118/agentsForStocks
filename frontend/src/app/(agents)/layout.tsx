import type { ReactNode } from "react"

import { AgentsTabs } from "@/components/features/common/agents-tabs"

/** Agents, Runs, Track record and Tokens & cost: one section, a tab each. */
export default function AgentsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <AgentsTabs />
      {children}
    </>
  )
}
