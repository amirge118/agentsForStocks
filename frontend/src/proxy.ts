import { NextResponse, type NextRequest } from "next/server"

import { checkBasicAuth } from "@/lib/basic-auth"

export interface DashboardAuthEnv {
  DASHBOARD_USER?: string
  DASHBOARD_PASSWORD?: string
  NODE_ENV?: string
}

/** Pure handler (env injected) so it can be tested; `proxy` wires in process.env. */
export function handleDashboardAuth(request: NextRequest, env: DashboardAuthEnv): NextResponse {
  const expected = env.DASHBOARD_PASSWORD
    ? { user: env.DASHBOARD_USER || "admin", password: env.DASHBOARD_PASSWORD }
    : null

  const decision = checkBasicAuth(
    request.headers.get("authorization"),
    expected,
    env.NODE_ENV === "production",
  )
  if (decision === "allow") return NextResponse.next()
  if (decision === "misconfigured") {
    return new NextResponse("Dashboard authentication is not configured (DASHBOARD_PASSWORD)", {
      status: 500,
    })
  }
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="agentsForStocks", charset="UTF-8"' },
  })
}

/** Protects every page and the backend proxy with the dashboard password. */
export function proxy(request: NextRequest): NextResponse {
  return handleDashboardAuth(request, {
    DASHBOARD_USER: process.env.DASHBOARD_USER,
    DASHBOARD_PASSWORD: process.env.DASHBOARD_PASSWORD,
    NODE_ENV: process.env.NODE_ENV,
  })
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
}
