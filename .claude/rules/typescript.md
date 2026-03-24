# TypeScript Rules — agentsForStocks

Enforced automatically on every `.ts` / `.tsx` file. No exceptions.

## Types

- Use `interface` for extensible object shapes (API responses, component props)
- Use `type` for unions, intersections, and aliases
- **Never use `any`** — use `unknown` with type narrowing or generics
- Use `Readonly<T>` and spread operators for immutability

```typescript
// Good
interface StockQuote {
  symbol: string
  price: number
  changePercent: number
}

type AgentStatus = "idle" | "running" | "error" | "completed"

// Bad
const data: any = await fetchStock()
```

## Validation

- Use **Zod** for all schema validation and type inference — at API boundaries, form inputs, and env vars
- Never trust raw API response shapes without validation

```typescript
const StockQuoteSchema = z.object({
  symbol: z.string().min(1).max(10),
  price: z.number().positive(),
  changePercent: z.number(),
})
type StockQuote = z.infer<typeof StockQuoteSchema>
```

## API Client

- **Never call `fetch()` directly from components or hooks**
- Use `get`/`post`/`put`/`del` from `@/lib/api/client.ts`
- All API response types must be defined in `@/types/`

## Logging

- **No `console.log` in production code** — use a logging library (e.g., `pino`)
- `console.log` is only acceptable in scripts and CLI tools, never in the app

## Data Access Pattern

Use the repository pattern for all data access — async interface with consistent method names:

```typescript
interface AgentRepository {
  getAll(): Promise<AgentRun[]>
  getById(id: string): Promise<AgentRun | null>
  getBySymbol(symbol: string): Promise<AgentRun[]>
  create(data: CreateAgentRunDto): Promise<AgentRun>
  update(id: string, data: Partial<AgentRun>): Promise<AgentRun>
}
```

## React / Next.js

- TanStack Query v5: use `isPending` (NOT `isLoading`), `useQueryClient()` hook
- On mutation success: `invalidateQueries`. On error: `toast({ variant: "destructive" })`
- Keep pages thin — business logic belongs in hooks and services, not in page components
- Error boundaries around agent status components (they can fail independently)

## Finance Formatting

- Currency: `toLocaleString("en-US", { style: "currency", currency: "USD" })`
- Percentages: `` `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` ``
- Prices: use `font-mono` CSS class; numeric tables: `tabular-nums`
