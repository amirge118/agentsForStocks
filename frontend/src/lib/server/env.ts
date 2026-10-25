import "server-only"

import { z } from "zod"

/**
 * Server-only configuration. Never import this from a client component — the
 * backend API key must not reach the browser ("server-only" enforces it at build).
 */
const ServerEnvSchema = z.object({
  BACKEND_URL: z.string().url().default("http://localhost:8000"),
  BACKEND_API_KEY: z.string().min(32).optional(),
})

export type ServerEnv = z.infer<typeof ServerEnvSchema>

export function serverEnv(): ServerEnv {
  return ServerEnvSchema.parse({
    BACKEND_URL: process.env.BACKEND_URL,
    BACKEND_API_KEY: process.env.BACKEND_API_KEY || undefined,
  })
}
