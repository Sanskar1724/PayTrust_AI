# PayTrust AI — API service image (docker-compose / Hugging Face Spaces / VPS)
# Phosphory: one lightweight container runs FastAPI (:8000). The Streamlit
# dashboard reuses the same image with a different command (see docker-compose.yml).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Persistent volume for SQLite
RUN mkdir -p /app/data && chmod -R a+rw /app/data

# Non-root user
RUN useradd -m paytrust && chown -R paytrust:paytrust /app
USER paytrust

EXPOSE 8000 8501

# Default command: API service (override with `streamlit` for the dashboard)
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]