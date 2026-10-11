import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from app.security.telegram import validate_telegram_init_data


def make_init_data(bot_token: str, auth_date: int, user_id: int = 1234) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "test-query",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_valid_init_data_is_accepted():
    data = make_init_data("test-token", 1_700_000_000)
    result = validate_telegram_init_data(data, "test-token", max_age_seconds=300, now=1_700_000_100)
    assert result["telegram_id"] == 1234


def test_tampered_init_data_is_rejected():
    data = make_init_data("test-token", 1_700_000_000).replace("Test", "Attacker")
    with pytest.raises(HTTPException) as exc:
        validate_telegram_init_data(data, "test-token", now=1_700_000_100)
    assert exc.value.status_code == 401


def test_expired_init_data_is_rejected():
    data = make_init_data("test-token", 1_700_000_000)
    with pytest.raises(HTTPException) as exc:
        validate_telegram_init_data(data, "test-token", max_age_seconds=60, now=1_700_000_100)
    assert exc.value.status_code == 401


def test_missing_bot_token_fails_closed():
    with pytest.raises(HTTPException) as exc:
        validate_telegram_init_data("auth_date=1", "")
    assert exc.value.status_code == 503
