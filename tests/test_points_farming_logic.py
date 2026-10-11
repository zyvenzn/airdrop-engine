from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.farming import claim_farming, start_farming
from app.services.points import InsufficientPoints, apply_points


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def __iter__(self):
        return iter(self.value if isinstance(self.value, list) else ([] if self.value is None else [self.value]))


class FakeSession:
    """Minimal service test double; database concurrency requires PostgreSQL integration tests."""
    def __init__(self, results=None):
        self.results = list(results or [])
        self.added = []
        self.flush_count = 0

    def scalar(self, statement):
        value = self.results.pop(0) if self.results else None
        return value

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1


def test_start_farming_sets_server_timed_session():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db = FakeSession([SimpleNamespace(id="user-1"), None])
    session = start_farming(db, user_id="user-1", now=now)
    assert session.started_at == now
    assert session.ends_at == now + timedelta(hours=8)
    assert session.reward_points == 80


def test_start_farming_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        start_farming(FakeSession(), user_id="user-1", points_per_hour=0)


def test_claim_farming_rejects_early_claim():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    farming = SimpleNamespace(
        id="farm-1", user_id="user-1", status="active",
        claimed_at=None, ends_at=now + timedelta(hours=1), reward_points=80,
    )
    with pytest.raises(ValueError, match="not complete"):
        claim_farming(FakeSession([SimpleNamespace(id="user-1", status="active"), farming]), user_id="user-1", session_id="farm-1", now=now)


def test_claim_farming_rejects_already_claimed():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    farming = SimpleNamespace(
        id="farm-1", user_id="user-1", status="claimed",
        claimed_at=now, ends_at=now - timedelta(seconds=1), reward_points=80,
    )
    with pytest.raises(ValueError, match="already claimed"):
        claim_farming(FakeSession([farming]), user_id="user-1", session_id="farm-1", now=now)


def test_apply_points_rejects_zero_and_bad_bucket():
    with pytest.raises(ValueError):
        apply_points(FakeSession(), user_id="u", amount=0, event_type="test", idempotency_key="k")
    with pytest.raises(ValueError):
        apply_points(FakeSession(), user_id="u", amount=1, event_type="test", idempotency_key="k", bucket="other")
