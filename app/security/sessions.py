"""Signed bearer sessions. Use HTTPS and keep SESSION_SECRET private."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import HTTPException, status

from app.config import settings


def _b64encode(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_session(*, user_id: str, telegram_id: int, now: int | None = None, ttl_seconds: int = 3600) -> str:
    secret = settings.session_secret
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    if not isinstance(user_id, str) or not user_id or len(user_id) > 128:
        raise ValueError("invalid session user id")
    if not isinstance(telegram_id, int) or isinstance(telegram_id, bool) or telegram_id <= 0:
        raise ValueError("telegram id must be a positive integer")
    if ttl_seconds < 60 or ttl_seconds > 86400:
        raise ValueError("session TTL must be between 60 and 86400 seconds")
    issued = int(time.time()) if now is None else now
    payload = {"sub": user_id, "tg": telegram_id, "iat": issued, "exp": issued + ttl_seconds}
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_session(token: str, *, now: int | None = None) -> dict:
    secret = settings.session_secret
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Session signing is not configured")
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(supplied_signature)):
            raise ValueError("bad signature")
        payload = json.loads(_b64decode(encoded))
        current = int(time.time()) if now is None else now
        if not isinstance(payload["sub"], str) or not payload["sub"]:
            raise ValueError("bad subject")
        if int(payload["tg"]) <= 0 or int(payload["exp"]) <= current or int(payload["iat"]) > current + 30:
            raise ValueError("invalid time or identity")
        if int(payload["exp"]) - int(payload["iat"]) > 86400:
            raise ValueError("session lifetime too long")
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session") from exc
