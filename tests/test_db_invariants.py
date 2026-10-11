"""Database-backed invariants using SQLite for fast local tests.

Run PostgreSQL integration tests separately before production; SQLite does not emulate
PostgreSQL row-level locking semantics.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import FarmingSession, PointBalance, PointsLedger, User
from app.services.points import InsufficientPoints, apply_points


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(telegram_id=10001, username="test-user", status="active")
        session.add(user)
        session.flush()
        session.add(PointBalance(user_id=user.id, available=100, pending=0))
        session.commit()
        session.info["test_user_id"] = user.id
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_points_ledger_is_idempotent(db):
    user_id = db.info["test_user_id"]
    with db.begin():
        first = apply_points(
            db, user_id=user_id, amount=25, event_type="test_reward",
            idempotency_key="test:stable-key", reference_id="ref-1",
        )
        second = apply_points(
            db, user_id=user_id, amount=25, event_type="test_reward",
            idempotency_key="test:stable-key", reference_id="ref-1",
        )
        assert first.id == second.id
    db.expire_all()
    balance = db.get(PointBalance, user_id)
    ledger = db.scalars(select(PointsLedger).where(PointsLedger.user_id == user_id)).all()
    assert balance.available == 125
    assert len(ledger) == 1


def test_points_reject_reused_key_for_different_operation(db):
    user_id = db.info["test_user_id"]
    with db.begin():
        apply_points(
            db, user_id=user_id, amount=10, event_type="test_reward",
            idempotency_key="test:conflict",
        )
        with pytest.raises(ValueError, match="idempotency key reused"):
            apply_points(
                db, user_id=user_id, amount=11, event_type="test_reward",
                idempotency_key="test:conflict",
            )


def test_insufficient_points_does_not_mutate_balance(db):
    user_id = db.info["test_user_id"]
    with pytest.raises(InsufficientPoints):
        with db.begin():
            apply_points(
                db, user_id=user_id, amount=-101, event_type="test_spend",
                idempotency_key="test:overspend",
            )
    db.expire_all()
    assert db.get(PointBalance, user_id).available == 100
    assert db.scalars(select(PointsLedger)).all() == []


def test_database_rejects_two_active_farming_sessions(db):
    user_id = db.info["test_user_id"]
    now = datetime.now(timezone.utc)
    with db.begin():
        db.add(FarmingSession(
            user_id=user_id, started_at=now, ends_at=now + timedelta(hours=8),
            reward_points=80, status="active",
        ))
        db.flush()
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(FarmingSession(
                    user_id=user_id, started_at=now, ends_at=now + timedelta(hours=8),
                    reward_points=80, status="active",
                ))
                db.flush()
    db.expire_all()
    active = db.scalars(
        select(FarmingSession).where(
            FarmingSession.user_id == user_id, FarmingSession.status == "active"
        )
    ).all()
    assert len(active) == 1
