"""Opt-in PostgreSQL concurrency tests.

Set TEST_DATABASE_URL to a dedicated, migrated test database. These tests create and
remove only their own uniquely identified user and related point rows; they never drop
tables or schemas.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import PointBalance, PointsLedger, User
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
                db.execute(delete(PointsLedger).where(PointsLedger.user_id == user.id))
                db.execute(delete(PointBalance).where(PointBalance.user_id == user.id))
                db.delete(user)
        engine.dispose()
