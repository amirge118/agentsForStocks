import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Self-contained server for the Docker image (frontend/Dockerfile)
  output: "standalone",
  poweredByHeader: false,
}

export default nextConfig
