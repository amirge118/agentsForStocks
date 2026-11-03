#!/bin/sh
# One command on your own machine: fill in what .env lacks, bring the whole stack up,
# then run every agent on one symbol and print the report. The dashboard stays up.
#
#   sh infra/deploy/try.sh               (AAPL)
#   sh infra/deploy/try.sh NVDA
#   sh infra/deploy/try.sh NVDA --force  (run again even if done today)
#
# Stop it with: docker compose down  (the data stays; `down -v` deletes it)
# Exit code: 0 PASS, 1 WARN, 2 FAIL.
set -eu

cd "$(dirname "$0")/../.."

docker info >/dev/null 2>&1 || {
	echo "Docker isn't running — start Docker Desktop and try again" >&2
	exit 2
}
if [ ! -e .env ]; then
	cp .env.example .env
	chmod 600 .env
	echo "Wrote .env from .env.example. Fill in FMP_API_KEY and GEMINI_API_KEY or GROQ_API_KEY, then run this again" >&2
	exit 2
fi

value() { sed -n "s/^$1=//p" .env | tail -n 1 | sed -e 's/[[:space:]]*#.*//' -e 's/[[:space:]]*$//'; }
secret() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c "$1"; }
set_value() {
	(umask 077 && grep -v "^$1=" .env >.env.tmp || true)
	printf '%s=%s\n' "$1" "$2" >>.env.tmp
	cat .env.tmp >.env
	rm .env.tmp
}

[ -n "$(value API_KEYS)" ] || set_value API_KEYS "$(secret 43)"
[ -n "$(value BACKEND_API_KEY)" ] || set_value BACKEND_API_KEY "$(value API_KEYS | cut -d, -f1)"
[ -n "$(value DASHBOARD_PASSWORD)" ] || set_value DASHBOARD_PASSWORD "$(secret 24)"
chmod 600 .env

# A Postgres on this machine usually holds 5432; the stack's own database moves aside.
if [ -z "$(value DB_PORT)" ] && [ -z "$(docker compose ps -q db 2>/dev/null)" ] &&
	nc -z 127.0.0.1 5432 2>/dev/null; then
	set_value DB_PORT 5433
	echo "Port 5432 is in use: the stack's database gets 5433 (DB_PORT in .env)"
fi

# The knowledge layer has its own profile, which this stack doesn't start.
export OPENVIKING_ENABLED=false

symbol=${1:-AAPL}
[ $# -eq 0 ] || shift

docker compose up -d --build --wait --wait-timeout 300

echo
echo "Dashboard: http://localhost:3000/runs  →  http://localhost:3000/symbols/$symbol"
echo "Login:     $(value DASHBOARD_USER | grep . || echo admin), password in .env (DASHBOARD_PASSWORD)"
echo

exec docker compose exec -e LOG_FORMAT=text api python -m scripts.verify "$symbol" "$@"
