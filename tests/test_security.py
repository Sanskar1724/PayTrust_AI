"""
tests/test_security.py — Phase 13 hardening.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import json

from database.database import init_db, get_connection
from core.security import assert_no_secrets_in_db, audit_log, sanitize_for_log, security_checklist

def _tmp_db():
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name) / "test.db"
    init_db(seed=True, db_path=p)
    return tmp, p

def _safe_cleanup(tmp):
    import gc, time
    gc.collect()
    time.sleep(0.05)
    try:
        tmp.cleanup()
    except PermissionError:
        gc.collect()
        time.sleep(0.1)
        try:
            tmp.cleanup()
        except Exception:
            pass

def test_no_secrets_in_db():
    tmp, dbp = _tmp_db()
    try:
        issues = assert_no_secrets_in_db(dbp)
        assert issues == []
    finally:
        _safe_cleanup(tmp)

def test_audit_log_redacts_secrets():
    tmp, dbp = _tmp_db()
    try:
        audit_log("req_123", "TEST_EVENT", "tester", "test_action", {"api_key": "sk-or-v1-secret", "amount": 100}, db_path=dbp)
        with get_connection(dbp) as conn:
            cur = conn.cursor()
            cur.execute("SELECT metadata FROM audit_logs WHERE request_id='req_123'")
            row = cur.fetchone()
            meta = json.loads(row["metadata"])
            assert meta["api_key"] == "***REDACTED***"
            assert meta["amount"] == 100
    finally:
        _safe_cleanup(tmp)

def test_sanitize_for_log():
    assert "***" in sanitize_for_log("api_key=sk-or-v1-abc123")
    assert len(sanitize_for_log("a"*1000)) < 600

def test_security_checklist_passes():
    tmp, dbp = _tmp_db()
    try:
        checklist = security_checklist(dbp)
        assert checklist["no_secrets_in_db"]["pass"] is True
        assert checklist["parameterized_sql"]["pass"] is True
        assert checklist["webhook_hmac"]["pass"] is True
    finally:
        _safe_cleanup(tmp)

def test_sql_injection_via_parameterized():
    tmp, dbp = _tmp_db()
    try:
        from database import repositories as repo
        # Attempt injection via merchant name — should be stored as literal, not executed
        m = repo.create_merchant("Robert'); DROP TABLE merchants; --", category="electronics", db_path=dbp)
        assert m["name"] == "Robert'); DROP TABLE merchants; --"
        # Table still exists
        with get_connection(dbp) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM merchants")
            assert cur.fetchone()[0] >= 5
    finally:
        _safe_cleanup(tmp)
