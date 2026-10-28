#!/bin/sh
# Migrate once, then start the workers. Fails fast if the database is unreachable.
set -e

export ARENA_BASE_URL="${ARENA_BASE_URL:-http://127.0.0.1:${PORT}}"

python -m app.cli init

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers "${WEB_CONCURRENCY}" \
    --proxy-headers \
    --forwarded-allow-ips "*" \
    --timeout-keep-alive 30
