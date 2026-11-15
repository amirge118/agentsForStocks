"use client"

import { createContext, useContext, type ReactNode } from "react"

import {
  agentRepository,
  llmRepository,
  outcomeRepository,
  portfolioRepository,
  runRepository,
  symbolRepository,
  watchlistRepository,
  type AgentRepository,
  type LLMRepository,
  type OutcomeRepository,
  type PortfolioRepository,
  type RunRepository,
  type SymbolRepository,
  type WatchlistRepository,
} from "./repositories"

export interface Repositories {
  symbols: SymbolRepository
  agents: AgentRepository
  runs: RunRepository
  llm: LLMRepository
  watchlist: WatchlistRepository
  outcomes: OutcomeRepository
  portfolio: PortfolioRepository
}

const defaultRepositories: Repositories = {
  symbols: symbolRepository,
  agents: agentRepository,
  runs: runRepository,
  llm: llmRepository,
  watchlist: watchlistRepository,
  outcomes: outcomeRepository,
  portfolio: portfolioRepository,
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
