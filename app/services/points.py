"""Transactional points service; call inside a SQLAlchemy Session transaction."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PointBalance, PointsLedger


class InsufficientPoints(ValueError):
    pass


def apply_points(
    db: Session,
    *,
    user_id: str,
    amount: int,
    event_type: str,
    idempotency_key: str,
    reference_id: str | None = None,
    bucket: str = "available",
) -> PointsLedger:
    if amount == 0:
        raise ValueError("amount must not be zero")
    if bucket not in {"available", "pending"}:
        raise ValueError("invalid balance bucket")
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("invalid idempotency key")

    existing = db.scalar(
        select(PointsLedger).where(PointsLedger.idempotency_key == idempotency_key)
    )
    if existing:
        if (
            existing.user_id != user_id
            or existing.amount != amount
            or existing.event_type != event_type
            or existing.reference_id != reference_id
            or existing.balance_bucket != bucket
        ):
            raise ValueError("idempotency key reused with different operation")
        return existing

    balance = db.scalar(
        select(PointBalance).where(PointBalance.user_id == user_id).with_for_update()
    )
    if balance is None:
        balance = PointBalance(user_id=user_id, available=0, pending=0)
        db.add(balance)
        db.flush()

    field = "available" if bucket == "available" else "pending"
    current = getattr(balance, field)
    if current + amount < 0:
        raise InsufficientPoints(f"insufficient {bucket} points")

    entry = PointsLedger(
        user_id=user_id,
        amount=amount,
        event_type=event_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        balance_bucket=bucket,
    )
    db.add(entry)
    setattr(balance, field, current + amount)
    db.add(balance)
    db.flush()
    return entry
