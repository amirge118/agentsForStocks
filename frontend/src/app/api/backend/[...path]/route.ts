/**
 * Backend proxy: /api/backend/<path> → ${BACKEND_URL}/api/v1/<path>.
 *
 * The browser only ever talks to this Next.js server; the backend API key is
 * attached here, from server-only env, so it never ships to the client.
 *
 * CSRF: the browser sends the dashboard's Basic-auth credentials automatically,
 * so state-changing requests must come from this origin and carry a JSON body
 * (a cross-site form or "simple" fetch can do neither without a CORS preflight).
 */
import { NextResponse, type NextRequest } from "next/server"

import { serverEnv } from "@/lib/server/env"

export const dynamic = "force-dynamic"

const SAFE_SEGMENT = /^[A-Za-z0-9._-]+$/

type Context = { params: Promise<{ path: string[] }> }

/**
 * Compare the browser's Origin with the host it actually addressed. Not
 * `nextUrl.origin`: in the Docker image the server binds HOSTNAME=0.0.0.0, so
 * nextUrl.origin is "http://0.0.0.0:3000" and every real request would look
 * cross-site. Behind a reverse proxy the public host is in X-Forwarded-Host
 * (a cross-site page cannot set that header without a CORS preflight).
 */
function isSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin")
  if (origin === null) return true // non-browser clients; browsers always send Origin on POST
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host")
  try {
    return host !== null && new URL(origin).host === host
  } catch {
    return false
  }
}

async function proxy(request: NextRequest, { params }: Context): Promise<NextResponse> {
  const { path } = await params
  // Reject traversal / encoded tricks — only plain path segments are forwarded
  if (path.length === 0 || !path.every((s) => SAFE_SEGMENT.test(s) && s !== "." && s !== "..")) {
    return NextResponse.json({ detail: "Invalid path" }, { status: 400 })
  }

  const isWrite = request.method !== "GET" && request.method !== "HEAD"
  if (isWrite) {
    if (!isSameOrigin(request)) {
      return NextResponse.json({ detail: "Cross-origin request refused" }, { status: 403 })
    }
    if (!request.headers.get("content-type")?.startsWith("application/json")) {
      return NextResponse.json({ detail: "Content-Type must be application/json" }, { status: 415 })
    }
  }

  const env = serverEnv()
  const target = new URL(`/api/v1/${path.join("/")}`, env.BACKEND_URL)
  target.search = request.nextUrl.search

  const headers = new Headers({ Accept: "application/json" })
  const contentType = request.headers.get("content-type")
  if (contentType) headers.set("Content-Type", contentType)
  if (env.BACKEND_API_KEY) headers.set("X-API-Key", env.BACKEND_API_KEY)

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: isWrite ? await request.text() : undefined,
      cache: "no-store",
    })
    // 204 / 304 carry no body, and a Response built with one throws
    const body = upstream.status === 204 || upstream.status === 304 ? null : await upstream.text()
    return new NextResponse(body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    })
  } catch {
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 502 })
  }
}

export { proxy as DELETE, proxy as GET, proxy as POST, proxy as PUT }
