"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState, type ReactNode } from "react"

import { Toaster } from "@/components/ui/toaster"
import { RepositoryProvider } from "@/lib/api/repository-context"

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } }),
  )
  return (
    <QueryClientProvider client={queryClient}>
      <RepositoryProvider>
        {children}
        <Toaster />
      </RepositoryProvider>
    </QueryClientProvider>
  )
}
