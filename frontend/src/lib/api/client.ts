/**
 * The only place the frontend performs HTTP. Components and hooks call the
 * per-domain repositories, which call get/post/put/del here. Every response is
 * validated with a Zod schema before it reaches the UI.
 *
 * Requests go to the same-origin proxy (src/app/api/backend), which adds the
 * backend API key server-side — the browser never sees it.
 */
import type { z } from "zod"

const API_BASE = "/api/backend"

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown = undefined,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

type Query = Readonly<Record<string, string | number | boolean | undefined | null>>

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) params.set(key, String(value))
  }
  const search = params.toString()
  return `${API_BASE}${path}${search ? `?${search}` : ""}`
}

async function request<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  schema: z.ZodType<T>,
  options: { query?: Query; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(buildUrl(path, options.query), {
    method,
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const payload: unknown = await response.json().catch(() => undefined)

  if (!response.ok) {
    const detail =
      payload !== null && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : undefined
    const message = typeof detail === "string" ? detail : `Request failed (${response.status})`
    throw new ApiError(message, response.status, detail)
  }

  const parsed = schema.safeParse(payload)
  if (!parsed.success) {
    throw new ApiError(`Unexpected response shape from ${path}`, response.status, parsed.error.issues)
  }
  return parsed.data
}

export function get<T>(path: string, schema: z.ZodType<T>, query?: Query): Promise<T> {
  return request("GET", path, schema, { query })
}

export function post<T>(path: string, schema: z.ZodType<T>, body: unknown): Promise<T> {
  return request("POST", path, schema, { body })
}

export function put<T>(path: string, schema: z.ZodType<T>, body: unknown): Promise<T> {
  return request("PUT", path, schema, { body })
}

export function del<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  return request("DELETE", path, schema)
}
