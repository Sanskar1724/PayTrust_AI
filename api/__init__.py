"""PayTrust AI — HTTP Service Layer.

Exposes the tested deterministic engines (Policy → Risk → Decision → Simulator)
and Razorpay webhook handling as a real REST API so merchants / AI agents can
programmatically consume PayTrust decisions.

Run locally:
    python -m api.main          # → http://localhost:8000  (Swagger at /docs)
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

This layer adds NO new business logic — it wraps already-tested modules.
"""