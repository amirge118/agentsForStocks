import { z } from "zod"

import { ApiError, del, get, post, put } from "@/lib/api/client"
import { agentRepository, runRepository, symbolRepository } from "@/lib/api/repositories"
import { overview, recommendation } from "@/test/fixtures"

function mockFetch(status: number, body: unknown): jest.Mock {
  const fn = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => (body === undefined ? Promise.reject(new Error("no body")) : Promise.resolve(body)),
  })
  global.fetch = fn as unknown as typeof fetch
  return fn
}

describe("api client", () => {
  it("builds /api/v1 URLs, drops empty query params and validates responses", async () => {
    const fetchMock = mockFetch(200, { ok: true })
    const result = await get("/things", z.object({ ok: z.boolean() }), { a: 1, b: undefined, c: null })
    expect(result).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith("/api/backend/things?a=1", {
      method: "GET",
      headers: undefined,
      body: undefined,
    })
  })

  it("sends JSON bodies for writes", async () => {
    const fetchMock = mockFetch(202, { id: "x" })
    await post("/things", z.object({ id: z.string() }), { force: true })
    expect(fetchMock.mock.calls[0][1]).toEqual({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: '{"force":true}',
    })
    await put("/things/1", z.object({ id: z.string() }), {})
    expect(fetchMock.mock.calls[1][1].method).toBe("PUT")
    await del("/things/1", z.object({ id: z.string() }))
    expect(fetchMock.mock.calls[2][1].method).toBe("DELETE")
  })

  it("raises ApiError with the backend detail message", async () => {
    mockFetch(404, { detail: "No recommendation for MSFT yet" })
    await expect(get("/x", z.unknown())).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "No recommendation for MSFT yet",
    })
  })

  it("raises a generic ApiError when the error body is not JSON or not a string", async () => {
    mockFetch(500, undefined)
    await expect(get("/x", z.unknown())).rejects.toThrow("Request failed (500)")
    mockFetch(422, { detail: [{ msg: "bad" }] })
    const error = await get("/x", z.unknown()).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).detail).toEqual([{ msg: "bad" }])
  })

  it("rejects responses that do not match the schema", async () => {
    mockFetch(200, { weighted_score: "not a number" })
    await expect(symbolRepository.getRecommendation("AAPL")).rejects.toThrow(
      "Unexpected response shape",
    )
  })
})

describe("repositories", () => {
  it("map filters to query params and parse responses", async () => {
    const fetchMock = mockFetch(200, overview)
    await expect(symbolRepository.getAll()).resolves.toEqual(overview)

    mockFetch(200, recommendation)
    await expect(symbolRepository.getRecommendation("BRK.B")).resolves.toEqual(recommendation)

    const resultsMock = mockFetch(200, [])
    await symbolRepository.getResults("AAPL", { agent: "moat", runDate: "2026-10-23" })
    expect(resultsMock.mock.calls[0][0]).toBe(
      "/api/backend/symbols/AAPL/results?agent=moat&run_date=2026-10-23",
    )

    const runsMock = mockFetch(200, [])
    await runRepository.getAll({ symbol: "AAPL", status: "failed", pipelineRunId: "p", limit: 5 })
    expect(runsMock.mock.calls[0][0]).toBe(
      "/api/backend/runs?symbol=AAPL&status=failed&pipeline_run_id=p&limit=5",
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe("agent repository", () => {
  it("lists agents", async () => {
    const profile = { provider: "anthropic", model: null, skills: ["moat_evidence"], use_llm: true }
    const agents = [{ name: "moat", description: "d", depends_on: [], recommendation_weight: 15, profile }]
    const fetchMock = mockFetch(200, agents)
    await expect(agentRepository.getAll()).resolves.toEqual(agents)
    expect(fetchMock.mock.calls[0][0]).toBe("/api/backend/agents")
  })

  it("posts pipeline runs", async () => {
    const accepted = { pipeline_run_id: "p", run_date: "2026-10-23", symbols: ["AAPL"], agents: [], force: true }
    const fetchMock = mockFetch(202, accepted)
    await expect(runRepository.create({ symbols: ["AAPL"], force: true })).resolves.toEqual(accepted)
    expect(fetchMock.mock.calls[0][0]).toBe("/api/backend/pipeline/runs")
  })

  it("uses default filters", async () => {
    const fetchMock = mockFetch(200, [])
    await runRepository.getAll()
    await symbolRepository.getResults("AAPL")
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "/api/backend/runs",
      "/api/backend/symbols/AAPL/results",
    ])
  })
})
