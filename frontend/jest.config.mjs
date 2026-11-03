import nextJest from "next/jest.js"

// Formatting tests assert exact dates; the app itself uses the viewer's time zone
process.env.TZ = "UTC"

const createJestConfig = nextJest({ dir: "./" })

/** @type {import("jest").Config} */
const config = {
  testEnvironment: "jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/src/$1" },
  testPathIgnorePatterns: ["<rootDir>/e2e/", "<rootDir>/.next/"],
  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/types/openapi.d.ts",
    "!src/test/**",
    "!src/app/**",
  ],
  coverageThreshold: { global: { lines: 80, branches: 75 } },
}

export default createJestConfig(config)
