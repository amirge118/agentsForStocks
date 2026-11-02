#!/bin/sh
# Bring the Docker stack up (if it isn't), then check everything end to end: keys and
# connectivity, every agent on a few symbols, and a report of the results.
#
#   sh infra/deploy/verify.sh                         (the watchlist)
#   sh infra/deploy/verify.sh AAPL NVDA JPM XOM JNJ
#   sh infra/deploy/verify.sh AAPL --force            (run again even if done today)
#
# Exit code: 0 PASS, 1 WARN, 2 FAIL.
set -eu

docker compose up -d --wait --wait-timeout 300
exec docker compose exec api python -m scripts.verify "$@"
