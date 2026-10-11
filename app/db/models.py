from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("telegram_id > 0", name="ck_users_telegram_id_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class PointBalance(Base):
    __tablename__ = "point_balances"
    __table_args__ = (
        CheckConstraint("available >= 0", name="ck_point_balances_available_nonnegative"),
        CheckConstraint("pending >= 0", name="ck_point_balances_pending_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    available: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pending: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PointsLedger(Base):
    __tablename__ = "points_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_points_ledger_idempotency_key"),
        CheckConstraint("amount != 0", name="ck_points_ledger_amount_nonzero"),
        CheckConstraint("balance_bucket IN ('available', 'pending')", name="ck_points_ledger_bucket"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    balance_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
