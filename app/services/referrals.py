from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PointsLedger, Referral, User
from app.services.points import apply_points


def attribute_referral(db: Session, *, referrer_id: str, referred_id: str) -> Referral:
    if referrer_id == referred_id:
        raise ValueError("self-referral is not allowed")
    users = db.scalars(
        select(User).where(User.id.in_([referrer_id, referred_id])).order_by(User.id).with_for_update()
    ).all()
    by_id = {user.id: user for user in users}
    referrer = by_id.get(referrer_id)
    referred = by_id.get(referred_id)
    if referrer is None or referred is None:
        raise ValueError("both users must exist")
    if referrer.status != "active" or referred.status != "active":
        raise ValueError("inactive users cannot be referred")

    existing = db.scalar(
        select(Referral).where(Referral.referred_id == referred_id).with_for_update()
    )
    if existing:
        if existing.referrer_id == referrer_id:
            return existing
        raise ValueError("referrer already assigned and cannot be changed")

    referral = Referral(referrer_id=referrer_id, referred_id=referred_id, status="pending")
    db.add(referral)
    db.flush()
    return referral


def qualify_referral(
    db: Session,
    *,
    referral_id: str,
    reward_points: int,
    now: datetime | None = None,
) -> Referral:
    if reward_points <= 0:
        raise ValueError("reward_points must be positive")
    referral = db.scalar(
        select(Referral).where(Referral.id == referral_id).with_for_update()
    )
    if referral is None:
        raise ValueError("referral not found")
    if referral.status == "qualified":
        existing_reward = db.scalar(
            select(PointsLedger).where(
                PointsLedger.idempotency_key == f"referral:{referral.id}"
            )
        )
        if existing_reward is None or existing_reward.amount != reward_points:
            raise ValueError("referral was already qualified with a different reward")
        return referral
    if referral.status != "pending":
        raise ValueError("referral is not eligible for qualification")

    # The referral status change and reward must be committed in the same DB transaction.
    apply_points(
        db,
        user_id=referral.referrer_id,
        amount=reward_points,
        event_type="referral_reward",
        idempotency_key=f"referral:{referral.id}",
        reference_id=referral.id,
    )
    referral.status = "qualified"
    referral.qualified_at = now or datetime.now(timezone.utc)
    db.add(referral)
    db.flush()
    return referral


BASE_DROP_PLAYS = 3
MAX_BONUS_DROP_PLAYS = 5


def count_qualified_referrals(db: Session, user_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(Referral.id)).where(
                Referral.referrer_id == user_id, Referral.status == "qualified"
            )
        ) or 0
    )


def bonus_drop_plays(qualified_referrals: int) -> int:
    return max(0, min(int(qualified_referrals), MAX_BONUS_DROP_PLAYS))


def daily_drop_limit(db: Session, user_id: str) -> int:
    return BASE_DROP_PLAYS + bonus_drop_plays(count_qualified_referrals(db, user_id))


def list_friends(db: Session, *, user_id: str, limit: int = 100) -> dict:
    rows = db.execute(
        select(Referral, User.username)
        .join(User, User.id == Referral.referred_id)
        .where(Referral.referrer_id == user_id)
        .order_by(Referral.created_at.desc())
        .limit(limit)
    ).all()
    rewards = {
        reference_id: int(amount)
        for reference_id, amount in db.execute(
            select(PointsLedger.reference_id, PointsLedger.amount).where(
                PointsLedger.user_id == user_id,
                PointsLedger.event_type == "referral_reward",
            )
        ).all()
    }
    items = [
        {
            "username": username or "Anonymous",
            "status": referral.status,
            "joined_at": referral.created_at,
            "qualified_at": referral.qualified_at,
            "reward_points": rewards.get(referral.id, 0),
        }
        for referral, username in rows
    ]
    qualified = count_qualified_referrals(db, user_id)
    total = int(
        db.scalar(select(func.count(Referral.id)).where(Referral.referrer_id == user_id)) or 0
    )
    return {
        "items": items,
        "total": total,
        "qualified": qualified,
        "pending": max(0, total - qualified),
        "points_earned": sum(rewards.values()),
        "bonus_drop_plays": bonus_drop_plays(qualified),
        "max_bonus_drop_plays": MAX_BONUS_DROP_PLAYS,
    }
