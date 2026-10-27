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
  const { DELETE, GET, POST } = await import("@/app/api/backend/[...path]/route")
  const handler = method === "GET" ? GET : method === "DELETE" ? DELETE : POST
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
      "{}", { ...json, origin: "https://evil.example", host: "dash" })
    expect(evil.status).toBe(403)

    const same = await call("POST", "http://dash/api/backend/pipeline/runs", ["pipeline", "runs"],
      "{}", { ...json, origin: "http://dash", host: "dash" })
    expect(same.status).toBe(202)

    const garbage = await call("POST", "http://dash/api/backend/pipeline/runs", ["pipeline", "runs"],
      "{}", { ...json, origin: "not a url", host: "dash" })
    expect(garbage.status).toBe(403)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("accepts same-origin writes when the server binds 0.0.0.0 (Docker)", async () => {
    // Regression: nextUrl.origin is http://0.0.0.0:3000 in the container, while the
    // browser sends Origin/Host for the address it used (localhost:3000).
    // a Response body can be read once — build a fresh one per call
    global.fetch = jest.fn().mockImplementation(async () => new Response("{}", { status: 202 }))
    const json = { "content-type": "application/json" }
    const docker = await call("POST", "http://0.0.0.0:3000/api/backend/pipeline/runs",
      ["pipeline", "runs"], "{}", { ...json, origin: "http://localhost:3000", host: "localhost:3000" })
    expect(docker.status).toBe(202)

    const proxied = await call("POST", "http://10.0.0.5:3000/api/backend/pipeline/runs",
      ["pipeline", "runs"], "{}",
      { ...json, origin: "https://stocks.example.com", host: "10.0.0.5:3000",
        "x-forwarded-host": "stocks.example.com" })
    expect(proxied.status).toBe(202)
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

  it("forwards a JSON DELETE and passes a 204 through without a body", async () => {
    const fetchMock = jest.fn().mockResolvedValue(new Response(null, { status: 204 }))
    global.fetch = fetchMock
    const resp = await call("DELETE", "http://dash/api/backend/watchlist/AAPL", ["watchlist", "AAPL"], undefined,
      { "content-type": "application/json", origin: "http://dash", host: "dash" })
    expect(resp.status).toBe(204)
    expect(await resp.text()).toBe("")
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE")
  })

  it("returns 502 when the backend is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValue(new TypeError("fetch failed"))
    const resp = await call("GET", "http://dash/api/backend/symbols", ["symbols"])
    expect(resp.status).toBe(502)
    expect(await resp.json()).toEqual({ detail: "Backend unavailable" })
  })
})
