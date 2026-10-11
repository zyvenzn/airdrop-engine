import pytest
from fastapi import HTTPException

from app.security.sessions import issue_session, verify_session


def test_session_round_trip(monkeypatch):
    monkeypatch.setattr("app.security.sessions.settings.session_secret", "x" * 48)
    token = issue_session(user_id="user-1", telegram_id=123, now=1000, ttl_seconds=600)
    payload = verify_session(token, now=1100)
    assert payload["sub"] == "user-1"
    assert payload["tg"] == 123
    assert payload["exp"] == 1600


def test_tampered_session_rejected(monkeypatch):
    monkeypatch.setattr("app.security.sessions.settings.session_secret", "x" * 48)
    token = issue_session(user_id="user-1", telegram_id=123, now=1000, ttl_seconds=600)
    with pytest.raises(HTTPException) as exc:
        verify_session(token + "tampered", now=1100)
    assert exc.value.status_code == 401


def test_expired_session_rejected(monkeypatch):
    monkeypatch.setattr("app.security.sessions.settings.session_secret", "x" * 48)
    token = issue_session(user_id="user-1", telegram_id=123, now=1000, ttl_seconds=600)
    with pytest.raises(HTTPException) as exc:
        verify_session(token, now=1600)
    assert exc.value.status_code == 401


def test_short_secret_fails_closed(monkeypatch):
    monkeypatch.setattr("app.security.sessions.settings.session_secret", "short")
    with pytest.raises(RuntimeError):
        issue_session(user_id="user-1", telegram_id=123, now=1000)
