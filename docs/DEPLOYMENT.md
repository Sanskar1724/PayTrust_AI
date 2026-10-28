# Deployment

PayTrust ships as **one Docker image** (`Dockerfile`). On start it runs migrations and creates the first admin (`python -m app.cli init`), then serves the API and the console on `$PORT`.

## What production needs

| | Required | Notes |
|---|---|---|
| PostgreSQL 14+ | yes | `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db` |
| Redis 6+ | for more than one instance | `REDIS_URL=redis://…`. Shared rate limits and live feed. |
| HTTPS | yes | Terminate TLS at the platform or a reverse proxy. Keep proxy buffering off for `/v1/stream` (SSE). |

### Environment

```bash
ENVIRONMENT=production
SECRET_KEY=<48+ random chars>
ADMIN_EMAIL=you@company.com
ADMIN_PASSWORD=<strong password>      # only used when no operator exists yet
CORS_ALLOW_ORIGINS=https://your-domain
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://...
SEED_DEMO_DATA=false                   # true for a demo instance
WEB_CONCURRENCY=2                      # workers per container
RAZORPAY_MODE=simulated | test | live  # test/live need RAZORPAY_KEY_ID, _KEY_SECRET, _WEBHOOK_SECRET
```

With `ENVIRONMENT=production`, startup is refused if `SECRET_KEY` or `ADMIN_PASSWORD` is a default, if CORS is `*`, or if the database is SQLite.

## Health and monitoring

* `GET /health`: the process is up (liveness).
* `GET /ready`: the database (and Redis) are reachable (readiness). Returns 503 if not.
* `GET /metrics`: Prometheus metrics (request counts and latency by route, decisions by type).
* Logs are JSON lines with a `request_id`. Every response carries an `X-Request-ID` header.

## Operations

```bash
python -m app.cli init                                     # migrate + bootstrap (idempotent)
PAYTRUST_PASSWORD=... python -m app.cli create-operator ops@company.com "Ops" reviewer
alembic revision --autogenerate -m "describe change"       # new migration after model changes
```

Back up PostgreSQL with your provider's automated backups and point-in-time recovery. Payments and the audit log are the system of record.

## Hosting options

Any platform that runs a Docker image with a managed PostgreSQL works. For example:

* **Render / Railway / Fly.io**: deploy the image, attach managed Postgres and Redis.
* **A single VM**: `docker compose up -d` with the included `docker-compose.yml`, behind Caddy or nginx for TLS.

Choosing and configuring the hosting is the next step after local verification.
