/**
 * HTTP Basic auth check for the dashboard (used by src/middleware.ts).
 * Edge-runtime safe: no Node crypto, constant-time comparison by hand.
 */

export interface DashboardCredentials {
  user: string
  password: string
}

export type AuthDecision = "allow" | "challenge" | "misconfigured"

function constantTimeEqual(a: string, b: string): boolean {
  const length = Math.max(a.length, b.length)
  let diff = a.length ^ b.length
  for (let i = 0; i < length; i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0)
  }
  return diff === 0
}

function decode(header: string | null): DashboardCredentials | null {
  if (!header?.startsWith("Basic ")) return null
  try {
    const decoded = atob(header.slice("Basic ".length))
    const separator = decoded.indexOf(":")
    if (separator < 0) return null
    return { user: decoded.slice(0, separator), password: decoded.slice(separator + 1) }
  } catch {
    return null
  }
}

/**
 * No password configured: allowed in development, refused in production
 * (fail closed). Otherwise the Authorization header must match.
 */
export function checkBasicAuth(
  authorization: string | null,
  expected: DashboardCredentials | null,
  production: boolean,
): AuthDecision {
  if (expected === null) return production ? "misconfigured" : "allow"
  const given = decode(authorization)
  if (given === null) return "challenge"
  const userOk = constantTimeEqual(given.user, expected.user)
  const passwordOk = constantTimeEqual(given.password, expected.password)
  return userOk && passwordOk ? "allow" : "challenge"
}
