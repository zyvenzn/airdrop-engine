"""Daily check-in streaks.

Streak state is derived from the points ledger (one `daily_checkin` entry per UTC day,
`reference_id` = ISO date), so there is no extra table to keep consistent with balances.
The per-day idempotency key guarantees at most one reward per user per day even under
concurrent requests.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PointsLedger, User
from app.services.points import apply_points

CHECKIN_EVENT = "daily_checkin"
# Reward per streak day; the 7-day cycle repeats while the streak continues.
STREAK_REWARDS: tuple[int, ...] = (10, 15, 20, 25, 30, 40, 50)
_HISTORY_LIMIT = 400


class AlreadyCheckedIn(ValueError):
    pass


def streak_reward(streak: int) -> int:
    if streak < 1:
        raise ValueError("streak must be at least 1")
    return STREAK_REWARDS[(streak - 1) % len(STREAK_REWARDS)]


def current_streak(days: set[date], today: date) -> int:
    """Consecutive check-in days ending today, or yesterday if today is not checked in yet."""
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _checkin_days(db: Session, user_id: str) -> set[date]:
    rows = db.scalars(
        select(PointsLedger.reference_id)
        .where(PointsLedger.user_id == user_id, PointsLedger.event_type == CHECKIN_EVENT)
        .order_by(PointsLedger.reference_id.desc())
        .limit(_HISTORY_LIMIT)
    ).all()
    days: set[date] = set()
    for value in rows:
        try:
            days.add(date.fromisoformat(value or ""))
        except ValueError:
            continue
    return days


def checkin_status(db: Session, *, user_id: str, today: date) -> dict:
    days = _checkin_days(db, user_id)
    checked_in = today in days
    streak = current_streak(days, today)
    next_streak = streak if checked_in else streak + 1
    return {
        "today": today.isoformat(),
        "checked_in_today": checked_in,
        "streak": streak,
        "next_reward": None if checked_in else streak_reward(next_streak),
        "cycle_rewards": list(STREAK_REWARDS),
        # 1-based position of the most recent check-in inside the 7-day cycle (0 = none yet).
        "cycle_day": ((streak - 1) % len(STREAK_REWARDS)) + 1 if streak else 0,
    }


def do_checkin(db: Session, *, user_id: str, today: date) -> dict:
    """Claim today's check-in. Call inside a caller-managed transaction."""
    # Lock the user first so the streak is computed against committed state.
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.status != "active":
        raise ValueError("account is not active")
    days = _checkin_days(db, user_id)
    if today in days:
        raise AlreadyCheckedIn("already checked in today")
    streak = current_streak(days, today) + 1
    reward = streak_reward(streak)
    day_key = today.isoformat()
    apply_points(
        db,
        user_id=user_id,
        amount=reward,
        event_type=CHECKIN_EVENT,
        reference_id=day_key,
        idempotency_key=f"checkin:{user_id}:{day_key}",
    )
    return {
        "today": day_key,
        "checked_in_today": True,
        "streak": streak,
        "awarded_points": reward,
        "next_reward": None,
        "cycle_rewards": list(STREAK_REWARDS),
        "cycle_day": ((streak - 1) % len(STREAK_REWARDS)) + 1,
    }
