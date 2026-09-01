"""
tests/test_razorpay.py — Phase 11 webhook signature + idempotency.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from pathlib import Path

from database.database import init_db
from services.razorpay_service import verify_webhook_signature, payload_hash, handle_webhook, record_event, is_duplicate_event

def _tmp_db():
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name) / "test.db"
    init_db(seed=False, db_path=p)
    return tmp, p

def test_verify_signature_correct():
    secret = "test_webhook_secret_123"
    body = json.dumps({"event":"payment.captured","id":"evt_123"}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret) is True
    assert verify_webhook_signature(body, "wrong", secret) is False

def test_verify_uses_raw_body_not_parsed():
    secret = "secret"
    body = b'{"a":1}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # Different serialization should fail
    body2 = b'{"a": 1}'  # space
    assert verify_webhook_signature(body2, sig, secret) is False

def test_payload_hash_deterministic():
    body = b"hello"
    assert payload_hash(body) == hashlib.sha256(body).hexdigest()

def test_idempotency_duplicate():
    tmp, dbp = _tmp_db()
    try:
        from services.razorpay_service import settings as razor_settings
        body = json.dumps({"id":"evt_dup","event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_123"}}}}).encode()
        # Use actual secret if configured, else any
        secret = razor_settings.RAZORPAY_WEBHOOK_SECRET or "test"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        res1 = handle_webhook(body, sig, db_path=dbp)
        assert res1["status"] in ("processed","duplicate")
        res2 = handle_webhook(body, sig, db_path=dbp)
        assert res2["status"] == "duplicate"
    finally:
        # Windows SQLite WAL lock — safe cleanup
        import gc, time
        gc.collect(); time.sleep(0.05)
        try:
            tmp.cleanup()
        except PermissionError:
            gc.collect(); time.sleep(0.1)
            try:
                tmp.cleanup()
            except Exception:
                pass

def test_handle_webhook_invalid_signature_rejected_when_secret_set(monkeypatch=None):
    # Simulate with secret set — monkeypatch settings
    from core.config import get_settings
    import services.razorpay_service as svc
    orig = svc.settings.RAZORPAY_WEBHOOK_SECRET
    try:
        svc.settings.RAZORPAY_WEBHOOK_SECRET = "mysecret"
        body = json.dumps({"id":"evt_bad_sig","event":"payment.captured"}).encode()
        # Wrong sig
        res = svc.handle_webhook(body, "bad", db_path=None)
        # This will try to use default DB path, but we check status
        assert res["status"] == "rejected"
        assert "signature" in res["reason"]
    finally:
        svc.settings.RAZORPAY_WEBHOOK_SECRET = orig

def test_handle_webhook_invalid_json():
    tmp, dbp = _tmp_db()
    try:
        # Need valid signature for this body to pass verification
        from services.razorpay_service import settings as razor_settings
        body = b"not json"
        secret = razor_settings.RAZORPAY_WEBHOOK_SECRET or "test"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        res = handle_webhook(body, sig, db_path=dbp)
        assert res["status"] == "rejected"
        assert "json" in res["reason"]
    finally:
        import gc, time
        gc.collect(); time.sleep(0.05)
        try:
            tmp.cleanup()
        except PermissionError:
            gc.collect(); time.sleep(0.1)
            try:
                tmp.cleanup()
            except Exception:
                pass
