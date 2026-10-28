"""Prometheus metrics, scraped from /metrics."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter("paytrust_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "paytrust_http_request_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
DECISIONS = Counter("paytrust_decisions_total", "Payment decisions issued", ["decision", "source"])
