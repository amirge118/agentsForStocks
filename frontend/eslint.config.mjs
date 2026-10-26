import nextVitals from "eslint-config-next/core-web-vitals"
import nextTypescript from "eslint-config-next/typescript"

const config = [
  ...nextVitals,
  ...nextTypescript,
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "no-console": "error",
    },
  },
  { ignores: ["next-env.d.ts", "coverage/**", "test-results/**", ".next/**", "node_modules/**", "src/types/openapi.d.ts", "playwright-report/**"] },
]

export default config
