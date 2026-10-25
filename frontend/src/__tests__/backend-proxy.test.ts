/**
 * @jest-environment node
 */
import { NextRequest } from "next/server"

jest.mock("server-only", () => ({}))

const KEY = "k".repeat(32)

async function call(
  method: string,
  url: string,
  path: string[],
  body?: string,
  headers: Record<string, string> = body ? { "content-type": "application/json" } : {},
) {
  const { GET, POST } = await import("@/app/api/backend/[...path]/route")
  const handler = method === "GET" ? GET : POST
  const request = new NextRequest(url, { method, body, headers })
  return handler(request, { params: Promise.resolve({ path }) })
}

describe("backend proxy", () => {
  const originalEnv = process.env

  beforeEach(() => {
    jest.resetModules()
    process.env = { ...originalEnv, BACKEND_URL: "http://backend:8000", BACKEND_API_KEY: KEY }
  })

  afterEach(() => {
    process.env = originalEnv
  })

  it("forwards path, query and body and adds the API key server-side", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      new Response('{"ok":true}', { status: 202, headers: { "content-type": "application/json" } }),
    )
    global.fetch = fetchMock

    const resp = await call(
      "POST", "http://dash/api/backend/pipeline/runs?x=1", ["pipeline", "runs"], '{"force":true}',
    )

    expect(resp.status).toBe(202)
    expect(await resp.json()).toEqual({ ok: true })
    const [target, init] = fetchMock.mock.calls[0]
    expect(String(target)).toBe("http://backend:8000/api/v1/pipeline/runs?x=1")
    expect(init.method).toBe("POST")
    expect(init.body).toBe('{"force":true}')
    expect(init.headers.get("X-API-Key")).toBe(KEY)
    expect(init.headers.get("Content-Type")).toBe("application/json")
  })

  it("passes backend errors through unchanged", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      new Response('{"detail":"Missing or invalid API key"}', {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    )
    const resp = await call("GET", "http://dash/api/backend/symbols", ["symbols"])
    expect(resp.status).toBe(401)
    expect(resp.headers.get("content-type")).toBe("application/json")
    expect(await resp.json()).toEqual({ detail: "Missing or invalid API key" })
  })

  it("omits the key header when none is configured", async () => {
    process.env.BACKEND_API_KEY = ""
    const fetchMock = jest.fn().mockResolvedValue(new Response("[]", { status: 200 }))
    global.fetch = fetchMock
    await call("GET", "http://dash/api/backend/agents", ["agents"])
    expect(fetchMock.mock.calls[0][1].headers.has("X-API-Key")).toBe(false)
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined()
  })

  it("rejects path traversal and empty paths", async () => {
    global.fetch = jest.fn()
    for (const path of [["..", "health"], ["a%2Fb"], ["."], []]) {
      const resp = await call("GET", "http://dash/api/backend/x", path)
      expect(resp.status).toBe(400)
    }
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it("refuses cross-origin writes (CSRF) but allows same-origin ones", async () => {
    const fetchMock = jest.fn().mockResolvedValue(new Response("{}", { status: 202 }))
    global.fetch = fetchMock
    const json = { "content-type": "application/json" }

    const evil = await call("POST", "http://dash/api/backend/pipeline/runs", ["pipeline", "runs"],
      "{}", { ...json, origin: "https://evil.example" })
    expect(evil.status).toBe(403)

    const same = await call("POST", "http://dash/api/backend/pipeline/runs", ["pipeline", "runs"],
      "{}", { ...json, origin: "http://dash" })
    expect(same.status).toBe(202)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("refuses writes without a JSON body (form / simple-request CSRF)", async () => {
    global.fetch = jest.fn()
    const form = await call("POST", "http://dash/api/backend/pipeline/runs", ["pipeline", "runs"],
      "force=true", { "content-type": "application/x-www-form-urlencoded" })
    expect(form.status).toBe(415)
    const plain = await call("POST", "http://dash/api/backend/pipeline/runs", ["pipeline", "runs"],
      "{}", { "content-type": "text/plain" })
    expect(plain.status).toBe(415)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it("returns 502 when the backend is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValue(new TypeError("fetch failed"))
    const resp = await call("GET", "http://dash/api/backend/symbols", ["symbols"])
    expect(resp.status).toBe(502)
    expect(await resp.json()).toEqual({ detail: "Backend unavailable" })
  })
})
