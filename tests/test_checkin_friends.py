from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import PointBalance, User
from app.services.checkin import AlreadyCheckedIn, STREAK_REWARDS, checkin_status, current_streak, do_checkin, streak_reward
from app.services.referrals import BASE_DROP_PLAYS, MAX_BONUS_DROP_PLAYS, bonus_drop_plays

DAY = date(2026, 11, 1)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_user(db, telegram_id: int) -> str:
    user = User(telegram_id=telegram_id, status="active")
    db.add(user)
    db.flush()
    db.add(PointBalance(user_id=user.id, available=0, pending=0))
    db.commit()
    return user.id


def test_streak_reward_schedule_and_wrap():
    assert [streak_reward(day) for day in range(1, 8)] == list(STREAK_REWARDS)
    assert streak_reward(8) == STREAK_REWARDS[0]
    with pytest.raises(ValueError):
        streak_reward(0)


def test_streak_continues_until_yesterday_and_breaks_on_gap():
    assert current_streak({DAY - timedelta(days=1), DAY - timedelta(days=2)}, DAY) == 2
    assert current_streak({DAY - timedelta(days=2)}, DAY) == 0


def test_checkin_awards_points_and_prevents_duplicate(db):
    user_id = make_user(db, 50001)
    result = do_checkin(db, user_id=user_id, today=DAY)
    db.commit()
    assert result["awarded_points"] == 10
    with pytest.raises(AlreadyCheckedIn):
        do_checkin(db, user_id=user_id, today=DAY)
    db.rollback()
    status = checkin_status(db, user_id=user_id, today=DAY)
    assert status["checked_in_today"] is True
    assert status["next_reward"] is None


def test_checkin_streak_resets_after_missed_day(db):
    user_id = make_user(db, 50002)
    for offset in range(3):
        do_checkin(db, user_id=user_id, today=DAY + timedelta(days=offset))
        db.commit()
    result = do_checkin(db, user_id=user_id, today=DAY + timedelta(days=4))
    db.commit()
    assert result["streak"] == 1
    assert result["awarded_points"] == STREAK_REWARDS[0]


def test_referral_bonus_is_capped():
    assert bonus_drop_plays(-1) == 0
    assert bonus_drop_plays(2) == 2
    assert bonus_drop_plays(99) == MAX_BONUS_DROP_PLAYS == 5
    assert BASE_DROP_PLAYS == 3
