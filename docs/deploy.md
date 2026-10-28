# Deploying agentsForStocks on a server

One Linux server with Docker runs the whole stack from `docker-compose.yml`: PostgreSQL,
the migrations, the API, the scheduler worker, the dashboard, Caddy (HTTPS) and a daily
database backup. About 30 minutes, most of it waiting for DNS and API keys.

```
internet ──443──▶ caddy ──▶ frontend:3000 ──▶ api:8000 ──▶ db:5432
                                               worker ──▶ db      backup ──▶ db → ./backups
```

Only Caddy listens on the internet (80, 443). Every other port is bound to `127.0.0.1`.

## 1. What you need

| | Where | Required |
|---|---|---|
| A server: 2 vCPU, 4 GB RAM, 40 GB disk, Ubuntu 24.04 | Hetzner (CX22), DigitalOcean, Lightsail, … | yes |
| A domain or subdomain whose DNS you control (e.g. `stocks.example.com`) | your registrar | yes, for HTTPS |
| `FMP_API_KEY` | financialmodelingprep.com (free: 250 calls/day, the pipeline uses ~12 per symbol) | yes |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | aistudio.google.com/apikey, console.groq.com/keys (free) | yes: they run the free model chain |
| `ANTHROPIC_API_KEY` | console.anthropic.com | recommended: the chain's last step, capped at `LLM_DAILY_BUDGET_USD` ($2/day) |
| `CEREBRAS_API_KEY` | cloud.cerebras.ai (free) | optional: one more free step |

## 2. Prepare the server

```sh
# Docker Engine + the compose plugin
curl -fsSL https://get.docker.com | sh

# Firewall: SSH and the web only — the database and the API stay private
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443
ufw enable
```

Point the domain at the server: an `A` record (and `AAAA` for IPv6) for
`stocks.example.com` → the server's address. Caddy can only get a certificate once
the name resolves to this machine.

## 3. Configure

```sh
git clone https://github.com/amirge118/agentsForStocks.git
cd agentsForStocks
sh infra/deploy/init-env.sh
```

`init-env.sh` writes `.env` (mode 600) from `.env.example` with fresh secrets: the API
key (`API_KEYS` = `BACKEND_API_KEY`), the dashboard password (printed once, so keep it)
and the database password. It also sets production values: `ENVIRONMENT=production`,
`SCHEDULER_ENABLED=true`, JSON logs, and the knowledge layer off.

Then edit `.env` and fill in:

```
DOMAIN=stocks.example.com
FMP_API_KEY=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...        # optional
```

Optional: `WATCHLIST` seeds the list on the first start only (default
AAPL, MSFT, NVDA, GOOGL, AMZN). After that, manage it from the dashboard.

## 4. Start

```sh
docker compose --profile https --profile backup up -d --build
docker compose ps        # db, api, worker, frontend, caddy, backup: running; migrate: exited (0)
```

## 5. Check it

```sh
# Keys and connectivity to Claude, FMP, Yahoo and SEC (exit 1 = something is not ready)
docker compose exec api python -m scripts.preflight

# Health: the scheduler runs in the worker
curl -s localhost:8000/health
# {"status":"ok","checks":{"database":"ok","scheduler":"external"},"jobs":{...}}

# A first run now, for one symbol (or press "Run analysis" on the dashboard)
docker compose exec api python -m scripts.run_pipeline AAPL
```

Open `https://stocks.example.com`, log in as `admin` with the printed password, and the
recommendation is on the watchlist.

The daily job runs at 18:30 New York time, Monday to Friday. After its first run,
`/health` shows `"daily_pipeline": "ok"`. `missed` or `failed` there means look at
`docker compose logs worker`. The job also settles past decisions, so the track record
fills in from ~20 trading days after the first run.

## 6. Day to day

| Task | Command |
|---|---|
| Logs | `docker compose logs -f worker api` |
| Upgrade to the latest `main` | `git pull && docker compose --profile https --profile backup up -d --build` (migrations run first) |
| What runs when | `docker compose exec api python -m scripts.schedules` |
| Token use and cost | `docker compose exec api python -m scripts.token_report --days 7` |
| Track record | `docker compose exec api python -m scripts.track_report` |
| Stop everything | `docker compose --profile https --profile backup down` (data stays in the volumes) |

## 7. Backups

The `backup` service writes `backups/agentsforstocks-<UTC time>.sql.gz` once a day and
keeps `BACKUP_KEEP_DAYS` (14) days. Copy them off the server too (e.g. a nightly
`rsync` or your provider's snapshots): a backup on the same disk doesn't survive the disk.

Restore into a running stack:

```sh
docker compose stop api worker
gunzip -c backups/agentsforstocks-<stamp>.sql.gz | \
  docker compose exec -T db psql -U postgres -d agentsforstocks
docker compose start api worker
```

(Restore into an empty database: drop and recreate it first, or run on a fresh volume.)

## 8. Monitoring (optional)

`OTEL_ENABLED=true` in `.env`, then add `--profile observability` to the `up` command.
Grafana listens on `127.0.0.1:3001`, so reach it over an SSH tunnel:
`ssh -L 3001:localhost:3001 user@server`, then open http://localhost:3001. Never open
port 3001 on the firewall: Grafana runs with anonymous admin access.

## Security notes

- The dashboard is behind Basic auth (`DASHBOARD_PASSWORD`), only over HTTPS through
  Caddy. The browser never sees the API key: the dashboard's server-side proxy adds it.
- `.env` holds every secret. Keep it at mode 600 and out of git (it is in `.gitignore`).
- The API (8000) and PostgreSQL (5432) are bound to 127.0.0.1. Reach them from the server
  itself or over an SSH tunnel.
