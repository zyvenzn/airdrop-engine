from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.security import dependencies


class FakeDB:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def scalar(self, statement):
        return self.result


def test_current_session_rejects_disabled_account(monkeypatch):
    user = SimpleNamespace(id="user-1", telegram_id=123, status="disabled")
    monkeypatch.setattr(dependencies, "verify_session", lambda token: {"sub": "user-1", "tg": 123})
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: FakeDB(user))

    with pytest.raises(HTTPException) as exc:
        dependencies.current_session("Bearer valid-signed-token")

    assert exc.value.status_code == 401
    assert exc.value.detail == "Session account is unavailable"


def test_current_session_rejects_telegram_identity_mismatch(monkeypatch):
    user = SimpleNamespace(id="user-1", telegram_id=456, status="active")
    monkeypatch.setattr(dependencies, "verify_session", lambda token: {"sub": "user-1", "tg": 123})
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: FakeDB(user))

    with pytest.raises(HTTPException) as exc:
        dependencies.current_session("Bearer valid-signed-token")

    assert exc.value.status_code == 401


def test_admin_dependency_rejects_disabled_admin(monkeypatch):
    admin = SimpleNamespace(id="admin-1", telegram_id=123, role="reviewer", status="disabled")
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: FakeDB(admin))
    dependency = dependencies.require_admin_roles("reviewer")

    with pytest.raises(HTTPException) as exc:
        dependency({"sub": "user-1", "tg": 123})

    assert exc.value.status_code == 403
    assert exc.value.detail == "Admin access required"


def test_admin_dependency_rejects_insufficient_role(monkeypatch):
    admin = SimpleNamespace(id="admin-1", telegram_id=123, role="analyst", status="active")
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: FakeDB(admin))
    dependency = dependencies.require_admin_roles("owner", "operator")

    with pytest.raises(HTTPException) as exc:
        dependency({"sub": "user-1", "tg": 123})

    assert exc.value.status_code == 403
    assert exc.value.detail == "Insufficient admin role"


def test_admin_dependency_returns_only_authorized_admin_identity(monkeypatch):
    admin = SimpleNamespace(id="admin-1", telegram_id=123, role="reviewer", status="active")
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: FakeDB(admin))
    dependency = dependencies.require_admin_roles("reviewer")

    result = dependency({"sub": "user-1", "tg": 123})

    assert result == {"admin_id": "admin-1", "telegram_id": 123, "role": "reviewer"}
