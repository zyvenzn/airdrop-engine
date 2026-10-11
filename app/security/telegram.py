"""Telegram Mini App initData validation. Never trust client-supplied user JSON alone."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, status


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> dict:
    if not bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram authentication is not configured",
        )
    if not init_data or len(init_data) > 16_384:
        raise HTTPException(status_code=401, detail="Invalid Telegram initData")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        values = dict(pairs)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Malformed Telegram initData") from exc

    supplied_hash = values.pop("hash", None)
    if not supplied_hash or "signature" in values and not supplied_hash:
        raise HTTPException(status_code=401, detail="Missing Telegram initData hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise HTTPException(status_code=401, detail="Invalid Telegram initData signature")

    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        telegram_id = int(user["id"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Telegram user data") from exc

    current_time = int(time.time()) if now is None else now
    age = current_time - auth_date
    if age < -30 or age > max_age_seconds:
        raise HTTPException(status_code=401, detail="Expired Telegram initData")
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Invalid Telegram user ID")

    return {"telegram_id": telegram_id, "user": user, "auth_date": auth_date}
