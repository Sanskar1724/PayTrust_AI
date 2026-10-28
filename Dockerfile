# PayTrust AI — one image: FastAPI API + the built React console, served from the same origin.

# ── 1. Build the frontend ──
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── 2. Runtime ──
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2 \
    AUTO_MIGRATE=false \
    LOG_JSON=true

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh

RUN useradd --create-home --uid 10001 paytrust \
    && mkdir -p /app/backend/data \
    && chown -R paytrust:paytrust /app/backend/data \
    && chmod +x /entrypoint.sh
USER paytrust

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=4 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=3)"

ENTRYPOINT ["/entrypoint.sh"]
