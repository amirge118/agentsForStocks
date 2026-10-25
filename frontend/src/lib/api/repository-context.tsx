"use client"

import { createContext, useContext, type ReactNode } from "react"

import {
  agentRepository,
  llmRepository,
  runRepository,
  symbolRepository,
  type AgentRepository,
  type LLMRepository,
  type RunRepository,
  type SymbolRepository,
} from "./repositories"

export interface Repositories {
  symbols: SymbolRepository
  agents: AgentRepository
  runs: RunRepository
  llm: LLMRepository
}

const defaultRepositories: Repositories = {
  symbols: symbolRepository,
  agents: agentRepository,
  runs: runRepository,
  llm: llmRepository,
}

const RepositoryContext = createContext<Repositories>(defaultRepositories)

export function RepositoryProvider({
  repositories,
  children,
}: {
  repositories?: Partial<Repositories>
  children: ReactNode
}) {
  return (
    <RepositoryContext.Provider value={{ ...defaultRepositories, ...repositories }}>
      {children}
    </RepositoryContext.Provider>
  )
}

export function useRepositories(): Repositories {
  return useContext(RepositoryContext)
}
