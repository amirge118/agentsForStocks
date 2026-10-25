import { dirname } from "path"
import { fileURLToPath } from "url"
import { FlatCompat } from "@eslint/eslintrc"

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) })

const config = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "no-console": "error",
    },
  },
  { ignores: ["next-env.d.ts", "coverage/**", "test-results/**", ".next/**", "node_modules/**", "src/types/openapi.d.ts", "playwright-report/**"] },
]

export default config
