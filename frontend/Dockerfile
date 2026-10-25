# syntax=docker/dockerfile:1
#
# Next.js standalone build. Runtime settings (BACKEND_URL, BACKEND_API_KEY,
# DASHBOARD_USER, DASHBOARD_PASSWORD) are read when the container starts —
# nothing secret is baked into the image.

# ---- deps ---------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- build --------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx next build

# ---- runtime: only the standalone server, non-root ----------------------------
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static

USER app
EXPOSE 3000

CMD ["node", "server.js"]
