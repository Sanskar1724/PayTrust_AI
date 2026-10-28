"""Credentials: operator passwords (bcrypt), operator sessions (JWT), agent API keys."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

import bcrypt
import jwt

from app.config import get_settings
from app.db import utcnow

JWT_ALGORITHM = "HS256"
KEY_PREFIX = "pt_"


# ── Passwords ──

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


# ── Operator sessions ──

def create_access_token(operator_id: int, role: str) -> str:
    s = get_settings()
    now = utcnow()
    payload = {
        "sub": str(operator_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.JWT_EXPIRE_MINUTES)).timestamp()),
        "typ": "operator",
    }
    return jwt.encode(payload, s.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_settings().SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == "operator" else None


# ── Agent API keys: pt_<8-char prefix>_<secret> ──

def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, sha256_of_secret). Only the prefix + hash are stored."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    return f"{KEY_PREFIX}{prefix}_{secret}", prefix, _digest(secret)


def parse_api_key(key: str) -> tuple[str, str] | None:
    """Split a presented key into (prefix, secret), or None if malformed."""
    if not key.startswith(KEY_PREFIX):
        return None
    body = key[len(KEY_PREFIX):]
    prefix, sep, secret = body.partition("_")
    if not sep or len(prefix) != 8 or not secret:
        return None
    return prefix, secret


def api_key_matches(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(_digest(secret), stored_hash)


def _digest(secret: str) -> str:
    # Keys carry 256 bits of entropy, so a fast hash is appropriate (no brute-force surface).
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
