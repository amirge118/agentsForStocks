#!/bin/sh
# Writes a production .env from .env.example with fresh secrets: one API key
# (API_KEYS = BACKEND_API_KEY), a dashboard password and a database password.
# Then fill in the provider keys and DOMAIN by hand. Refuses to overwrite .env.
#
#   sh infra/deploy/init-env.sh            (from the repository root)
set -eu

if [ -e .env ]; then
	echo ".env already exists — not overwriting it" >&2
	exit 1
fi

secret() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c "$1"; }
api_key=$(secret 43)
dashboard_password=$(secret 24)
db_password=$(secret 32)

sed \
	-e "s|^ENVIRONMENT=.*|ENVIRONMENT=production|" \
	-e "s|^API_KEYS=.*|API_KEYS=$api_key|" \
	-e "s|^BACKEND_API_KEY=.*|BACKEND_API_KEY=$api_key|" \
	-e "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=$dashboard_password|" \
	-e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$db_password|" \
	-e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://postgres:$db_password@localhost:5432/agentsforstocks|" \
	-e "s|^LOG_FORMAT=.*|LOG_FORMAT=json|" \
	-e "s|^SCHEDULER_ENABLED=.*|SCHEDULER_ENABLED=true|" \
	-e "s|^OPENVIKING_ENABLED=.*|OPENVIKING_ENABLED=false|" \
	-e "s|^ANTHROPIC_API_KEY=your_anthropic_api_key_here|ANTHROPIC_API_KEY=|" \
	-e "s|^FMP_API_KEY=your_fmp_api_key_here .*|FMP_API_KEY=|" \
	-e "s|^ALPHA_VANTAGE_KEY=.*|ALPHA_VANTAGE_KEY=|" \
	.env.example > .env
chmod 600 .env

echo "Wrote .env (mode 600). Dashboard login: admin / $dashboard_password"
echo "Still to fill in: FMP_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY (optional),"
echo "DOMAIN and ACME_EMAIL (for HTTPS). Then: docker compose --profile https --profile backup up -d --build"
