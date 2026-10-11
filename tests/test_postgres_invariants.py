"""Opt-in PostgreSQL concurrency tests.

Set TEST_DATABASE_URL to a dedicated, migrated test database. These tests create and
remove only their own uniquely identified user and related point rows; they never drop
tables or schemas.
"""
import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import FarmingSession, PointBalance, PointsLedger, User
from app.services.farming import claim_farming, start_farming
from app.services.points import apply_points


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set TEST_DATABASE_URL to run PostgreSQL integration tests"
)


def test_concurrent_retry_applies_points_once():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    telegram_id = 8_000_000_000 + int(uuid4().int % 1_000_000_000)
    idempotency_key = f"postgres-concurrency:{uuid4()}"

    try:
        with SessionFactory.begin() as db:
            user = User(telegram_id=telegram_id, username="pg-concurrency-test", status="active")
            db.add(user)
            db.flush()
            user_id = user.id
            db.add(PointBalance(user_id=user_id, available=100, pending=0))

        barrier = Barrier(2)

        def apply_once():
            barrier.wait(timeout=10)
            with SessionFactory.begin() as db:
                entry = apply_points(
                    db,
                    user_id=user_id,
                    amount=25,
                    event_type="integration_test",
                    idempotency_key=idempotency_key,
                    reference_id="concurrent-retry",
                )
                return entry.id

        with ThreadPoolExecutor(max_workers=2) as pool:
            entry_ids = list(pool.map(lambda _: apply_once(), range(2)))

        assert entry_ids[0] == entry_ids[1]
        with SessionFactory() as db:
            balance = db.scalar(select(PointBalance).where(PointBalance.user_id == user_id))
            entries = db.scalars(
                select(PointsLedger).where(PointsLedger.idempotency_key == idempotency_key)
            ).all()
            assert balance is not None
            assert balance.available == 125
            assert len(entries) == 1
    finally:
        # Delete only records created by this test.
        with SessionFactory.begin() as db:
            user = db.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is not None:
                db.execute(delete(FarmingSession).where(FarmingSession.user_id == user.id))
                db.execute(delete(PointsLedger).where(PointsLedger.user_id == user.id))
                db.execute(delete(PointBalance).where(PointBalance.user_id == user.id))
                db.delete(user)
        engine.dispose()


def test_concurrent_farming_claim_rewards_once():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    telegram_id = 8_000_000_000 + int(uuid4().int % 1_000_000_000)
    now = datetime.now(timezone.utc)

    try:
        with SessionFactory.begin() as db:
            user = User(telegram_id=telegram_id, username="pg-farming-test", status="active")
            db.add(user)
            db.flush()
            user_id = user.id
            db.add(PointBalance(user_id=user_id, available=0, pending=0))
            farming = FarmingSession(
                user_id=user_id,
                started_at=now - timedelta(hours=8),
                ends_at=now - timedelta(seconds=1),
                reward_points=80,
                status="active",
            )
            db.add(farming)
            db.flush()
            farming_id = farming.id

        barrier = Barrier(2)

        def claim_once():
            barrier.wait(timeout=10)
            try:
                with SessionFactory.begin() as db:
                    claim_farming(db, user_id=user_id, session_id=farming_id, now=now)
                return "claimed"
            except ValueError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: claim_once(), range(2)))

        assert outcomes.count("claimed") == 1
        assert outcomes.count("rejected") == 1
        with SessionFactory() as db:
            balance = db.scalar(select(PointBalance).where(PointBalance.user_id == user_id))
            entries = db.scalars(select(PointsLedger).where(
                PointsLedger.user_id == user_id,
                PointsLedger.idempotency_key == f"farming:{farming_id}",
            )).all()
            farming = db.get(FarmingSession, farming_id)
            assert balance is not None and balance.available == 80
            assert len(entries) == 1
            assert farming.status == "claimed"
    finally:
        with SessionFactory.begin() as db:
            user = db.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is not None:
                db.execute(delete(FarmingSession).where(FarmingSession.user_id == user.id))
                db.execute(delete(PointsLedger).where(PointsLedger.user_id == user.id))
                db.execute(delete(PointBalance).where(PointBalance.user_id == user.id))
                db.delete(user)
        engine.dispose()


def test_concurrent_farming_start_creates_only_one_active_session():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    telegram_id = 8_000_000_000 + int(uuid4().int % 1_000_000_000)
    now = datetime.now(timezone.utc)

    try:
        with SessionFactory.begin() as db:
            user = User(telegram_id=telegram_id, username="pg-farming-start-test", status="active")
            db.add(user)
            db.flush()
            user_id = user.id

        barrier = Barrier(2)

        def start_once():
            barrier.wait(timeout=10)
            try:
                with SessionFactory.begin() as db:
                    start_farming(db, user_id=user_id, now=now)
                return "started"
            except ValueError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: start_once(), range(2)))

        assert outcomes.count("started") == 1
        assert outcomes.count("rejected") == 1
        with SessionFactory() as db:
            active = db.scalars(select(FarmingSession).where(
                FarmingSession.user_id == user_id,
                FarmingSession.status == "active",
            )).all()
            assert len(active) == 1
    finally:
        with SessionFactory.begin() as db:
            user = db.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is not None:
                db.execute(delete(FarmingSession).where(FarmingSession.user_id == user.id))
                db.execute(delete(PointsLedger).where(PointsLedger.user_id == user.id))
                db.execute(delete(PointBalance).where(PointBalance.user_id == user.id))
                db.delete(user)
        engine.dispose()
