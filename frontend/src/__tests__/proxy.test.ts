/**
 * @jest-environment node
 */
import { NextRequest } from "next/server"

import { handleDashboardAuth, proxy } from "@/proxy"

function request(authorization?: string): NextRequest {
  return new NextRequest("http://dash/", {
    headers: authorization ? { authorization } : undefined,
  })
}

const passed = (r: Response) => r.headers.get("x-middleware-next") === "1"

describe("dashboard auth", () => {
  it("challenges, then allows the configured credentials", () => {
    const env = { DASHBOARD_USER: "amir", DASHBOARD_PASSWORD: "s3cret-pass", NODE_ENV: "production" }
    const challenge = handleDashboardAuth(request(), env)
    expect(challenge.status).toBe(401)
    expect(challenge.headers.get("www-authenticate")).toContain("Basic")
    expect(passed(handleDashboardAuth(request(`Basic ${btoa("amir:s3cret-pass")}`), env))).toBe(true)
  })

  it("defaults the user to admin", () => {
    const env = { DASHBOARD_PASSWORD: "pw", NODE_ENV: "production" }
    expect(passed(handleDashboardAuth(request(`Basic ${btoa("admin:pw")}`), env))).toBe(true)
  })

  it("fails closed in production without a password, allows in development", () => {
    expect(handleDashboardAuth(request(), { NODE_ENV: "production" }).status).toBe(500)
    expect(passed(handleDashboardAuth(request(), { NODE_ENV: "development" }))).toBe(true)
  })

  it("proxy reads process.env", () => {
    const env = process.env as Record<string, string | undefined>
    const saved = env.DASHBOARD_PASSWORD
    env.DASHBOARD_PASSWORD = "from-env"
    try {
      expect(proxy(request()).status).toBe(401)
    } finally {
      env.DASHBOARD_PASSWORD = saved
    }
  })
})
