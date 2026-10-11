from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FarmingSession, User
from app.services.points import apply_points


def start_farming(
    db: Session,
    *,
    user_id: str,
    points_per_hour: int = 10,
    duration_hours: int = 8,
    now: datetime | None = None,
) -> FarmingSession:
    if points_per_hour <= 0 or duration_hours <= 0 or duration_hours > 24:
        raise ValueError("invalid farming configuration")
    current = now or datetime.now(timezone.utc)
    # Lock the parent user row first; an empty active-session query cannot serialize concurrent starts.
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ValueError("user not found")
    if user.status != "active":
        raise ValueError("account is not active")
    active = db.scalar(
        select(FarmingSession)
        .where(FarmingSession.user_id == user_id, FarmingSession.status == "active")
        .with_for_update()
    )
    if active:
        raise ValueError("an active farming session already exists")
    session = FarmingSession(
        user_id=user_id,
        started_at=current,
        ends_at=current + timedelta(hours=duration_hours),
        reward_points=points_per_hour * duration_hours,
        status="active",
    )
    db.add(session)
    db.flush()
    return session


def claim_farming(
    db: Session,
    *,
    user_id: str,
    session_id: str,
    now: datetime | None = None,
) -> FarmingSession:
    current = now or datetime.now(timezone.utc)
    session = db.scalar(
        select(FarmingSession)
        .where(FarmingSession.id == session_id, FarmingSession.user_id == user_id)
        .with_for_update()
    )
    if session is None:
        raise ValueError("farming session not found")
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.status != "active":
        raise ValueError("account is not active")
    if session.status != "active" or session.claimed_at is not None:
        raise ValueError("farming session already claimed or inactive")
    if current < session.ends_at:
        raise ValueError("farming session is not complete")

    apply_points(
        db,
        user_id=user_id,
        amount=session.reward_points,
        event_type="farming_claim",
        idempotency_key=f"farming:{session.id}",
        reference_id=session.id,
    )
    session.status = "claimed"
    session.claimed_at = current
    db.add(session)
    db.flush()
    return session
