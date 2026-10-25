import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderResult } from "@testing-library/react"
import type { ReactElement } from "react"

import { Toaster } from "@/components/ui/toaster"
import { RepositoryProvider, type Repositories } from "@/lib/api/repository-context"

/** Render with a fresh QueryClient (no retries) and in-memory repositories. */
export function renderWithProviders(
  ui: ReactElement,
  repositories: Partial<Repositories> = {},
): RenderResult & { queryClient: QueryClient } {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RepositoryProvider repositories={repositories}>
        {ui}
        <Toaster />
      </RepositoryProvider>
    </QueryClientProvider>,
  )
  return { ...result, queryClient }
}

/** A promise that never settles — keeps a query in its pending state. */
export function pending<T>(): Promise<T> {
  return new Promise<T>(() => undefined)
}
