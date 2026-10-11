"""Transactional, idempotent points mutations.

Call these functions inside a caller-managed SQLAlchemy transaction. Locking the parent
user before checking the ledger serializes point mutations for that user on PostgreSQL,
so a concurrent retry observes the committed idempotency record.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PointBalance, PointsLedger, User


class InsufficientPoints(ValueError):
    pass


class IdempotencyConflict(ValueError):
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

    # Serialize all point mutations for this account before reading the ledger.
    # PostgreSQL READ COMMITTED then lets a waiting retry see the prior commit.
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ValueError("user not found")

    existing = db.scalar(
        select(PointsLedger).where(PointsLedger.idempotency_key == idempotency_key)
    )
    if existing:
        _assert_same_operation(
            existing,
            user_id=user_id,
            amount=amount,
            event_type=event_type,
            reference_id=reference_id,
            bucket=bucket,
        )
        return existing

    # The caller must use a transaction context so failures roll back both writes.
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
    setattr(balance, field, current + amount)
    db.add(balance)
    db.add(entry)
    # The unique ledger key remains the final guard, including cross-account key reuse.
    db.flush()
    return entry


def _assert_same_operation(
    existing: PointsLedger,
    *,
    user_id: str,
    amount: int,
    event_type: str,
    reference_id: str | None,
    bucket: str,
) -> None:
    if (
        existing.user_id != user_id
        or existing.amount != amount
        or existing.event_type != event_type
        or existing.reference_id != reference_id
        or existing.balance_bucket != bucket
    ):
        raise IdempotencyConflict("idempotency key reused with different operation")
