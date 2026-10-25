import { checkBasicAuth } from "@/lib/basic-auth"

const creds = { user: "admin", password: "s3cret-pass" }
const header = (user: string, password: string) => `Basic ${btoa(`${user}:${password}`)}`

describe("checkBasicAuth", () => {
  it("allows the right credentials (password may contain ':')", () => {
    expect(checkBasicAuth(header("admin", "s3cret-pass"), creds, true)).toBe("allow")
    const colon = { user: "u", password: "a:b" }
    expect(checkBasicAuth(header("u", "a:b"), colon, true)).toBe("allow")
  })

  it.each([
    ["missing header", null],
    ["wrong password", header("admin", "nope")],
    ["wrong user", header("root", "s3cret-pass")],
    ["prefix of the password", header("admin", "s3cret")],
    ["not basic", "Bearer abc"],
    ["bad base64", "Basic %%%"],
    ["no separator", `Basic ${btoa("adminonly")}`],
  ])("challenges %s", (_name, value) => {
    expect(checkBasicAuth(value, creds, true)).toBe("challenge")
  })

  it("fails closed in production when no password is configured", () => {
    expect(checkBasicAuth(null, null, true)).toBe("misconfigured")
    expect(checkBasicAuth(null, null, false)).toBe("allow")
  })
})
