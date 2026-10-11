"""Check-in streak, friends list and referral Drop-ticket logic (SQLite-backed)."""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import PointBalance, User
from app.services.checkin import (
    STREAK_REWARDS,
    AlreadyCheckedIn,
    checkin_status,
    current_streak,
    do_checkin,
    streak_reward,
)
from app.services.referrals import (
    BASE_DROP_PLAYS,
    MAX_BONUS_DROP_PLAYS,
    attribute_referral,
    bonus_drop_plays,
    daily_drop_limit,
    list_friends,
    qualify_referral,
)

DAY0 = date(2026, 11, 1)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_user(db, telegram_id: int, username: str | None = None) -> str:
    user = User(telegram_id=telegram_id, username=username, status="active")
    db.add(user)
    db.flush()
    db.add(PointBalance(user_id=user.id, available=0, pending=0))
    db.commit()
    return user.id


def balance(db, user_id: str) -> int:
    return db.get(PointBalance, user_id).available


def test_streak_reward_cycles_every_seven_days():
    assert [streak_reward(n) for n in range(1, 8)] == list(STREAK_REWARDS)
    assert streak_reward(8) == STREAK_REWARDS[0]
    assert streak_reward(14) == STREAK_REWARDS[-1]
    with pytest.raises(ValueError):
        streak_reward(0)


def test_current_streak_anchors_on_today_or_yesterday():
    days = {DAY0 - timedelta(days=n) for n in (1, 2, 3)}
    assert current_streak(days, DAY0) == 3  # today not claimed yet, streak still alive
    assert current_streak(days | {DAY0}, DAY0) == 4
    assert current_streak({DAY0 - timedelta(days=2)}, DAY0) == 0  # gap breaks it
    assert current_streak(set(), DAY0) == 0


def test_checkin_awards_growing_rewards_and_blocks_double_claim(db):
    uid = make_user(db, 20001)
    first = do_checkin(db, user_id=uid, today=DAY0)
    db.commit()
    assert (first["streak"], first["awarded_points"]) == (1, 10)

    with pytest.raises(AlreadyCheckedIn):
        do_checkin(db, user_id=uid, today=DAY0)
    db.rollback()

    second = do_checkin(db, user_id=uid, today=DAY0 + timedelta(days=1))
    db.commit()
    assert (second["streak"], second["awarded_points"]) == (2, 15)
    assert balance(db, uid) == 25


def test_checkin_streak_resets_after_missed_day(db):
    uid = make_user(db, 20002)
    for offset in (0, 1, 2):
        do_checkin(db, user_id=uid, today=DAY0 + timedelta(days=offset))
        db.commit()
    skipped = do_checkin(db, user_id=uid, today=DAY0 + timedelta(days=4))
    db.commit()
    assert (skipped["streak"], skipped["awarded_points"]) == (1, STREAK_REWARDS[0])


def test_checkin_cycle_wraps_after_seven_days(db):
    uid = make_user(db, 20003)
    results = []
    for offset in range(8):
        results.append(do_checkin(db, user_id=uid, today=DAY0 + timedelta(days=offset)))
        db.commit()
    assert [r["awarded_points"] for r in results[:7]] == list(STREAK_REWARDS)
    assert results[7]["streak"] == 8
    assert results[7]["awarded_points"] == STREAK_REWARDS[0]
    assert results[7]["cycle_day"] == 1


def test_checkin_status_reflects_claim(db):
    uid = make_user(db, 20004)
    before = checkin_status(db, user_id=uid, today=DAY0)
    assert before["checked_in_today"] is False
    assert (before["streak"], before["next_reward"]) == (0, 10)

    do_checkin(db, user_id=uid, today=DAY0)
    db.commit()
    after = checkin_status(db, user_id=uid, today=DAY0)
    assert after["checked_in_today"] is True
    assert (after["streak"], after["next_reward"]) == (1, None)

    tomorrow = checkin_status(db, user_id=uid, today=DAY0 + timedelta(days=1))
    assert (tomorrow["checked_in_today"], tomorrow["streak"], tomorrow["next_reward"]) == (False, 1, 15)


def test_checkin_rejects_inactive_account(db):
    uid = make_user(db, 20005)
    db.get(User, uid).status = "disabled"
    db.commit()
    with pytest.raises(ValueError, match="not active"):
        do_checkin(db, user_id=uid, today=DAY0)


def test_bonus_drop_plays_is_capped():
    assert bonus_drop_plays(-3) == 0
    assert bonus_drop_plays(2) == 2
    assert bonus_drop_plays(99) == MAX_BONUS_DROP_PLAYS


def test_pending_friends_give_no_tickets_but_qualified_do(db):
    owner = make_user(db, 30001, "owner")
    friend_a = make_user(db, 30002, "friend_a")
    friend_b = make_user(db, 30003, None)

    referral_a = attribute_referral(db, referrer_id=owner, referred_id=friend_a)
    attribute_referral(db, referrer_id=owner, referred_id=friend_b)
    db.commit()

    assert daily_drop_limit(db, owner) == BASE_DROP_PLAYS
    pending = list_friends(db, user_id=owner)
    assert (pending["total"], pending["qualified"], pending["pending"]) == (2, 0, 2)
    assert pending["bonus_drop_plays"] == 0

    qualify_referral(db, referral_id=referral_a.id, reward_points=100)
    db.commit()

    assert daily_drop_limit(db, owner) == BASE_DROP_PLAYS + 1
    friends = list_friends(db, user_id=owner)
    assert (friends["total"], friends["qualified"], friends["pending"]) == (2, 1, 1)
    assert friends["points_earned"] == 100
    assert friends["bonus_drop_plays"] == 1
    by_name = {item["username"]: item for item in friends["items"]}
    assert by_name["friend_a"]["status"] == "qualified"
    assert by_name["friend_a"]["reward_points"] == 100
    assert by_name["Anonymous"]["status"] == "pending"
    assert by_name["Anonymous"]["reward_points"] == 0


def test_friends_list_is_scoped_to_the_referrer(db):
    owner = make_user(db, 40001)
    other = make_user(db, 40002)
    stranger = make_user(db, 40003, "stranger")
    attribute_referral(db, referrer_id=other, referred_id=stranger)
    db.commit()
    assert list_friends(db, user_id=owner)["items"] == []
    assert list_friends(db, user_id=other)["total"] == 1
