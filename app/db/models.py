from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
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


class FarmingSession(Base):
    __tablename__ = "farming_sessions"
    __table_args__ = (
        CheckConstraint("ends_at > started_at", name="ck_farming_session_positive_duration"),
        CheckConstraint("status IN ('active', 'claimed', 'expired', 'cancelled')", name="ck_farming_session_status"),
        CheckConstraint("reward_points > 0", name="ck_farming_reward_positive"),
        Index("uq_farming_one_active_per_user", "user_id", unique=True, postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("reward_points > 0", name="ck_tasks_reward_positive"),
        CheckConstraint("status IN ('draft', 'active', 'paused', 'archived')", name="ck_tasks_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class TaskSubmission(Base):
    __tablename__ = "task_submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "task_id", name="uq_task_submission_user_task"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_task_submission_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    evidence: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_id", name="uq_referrals_referred_once"),
        CheckConstraint("referrer_id != referred_id", name="ck_referrals_no_self_referral"),
        CheckConstraint("status IN ('pending', 'qualified', 'rejected')", name="ck_referrals_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    referrer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False)
    referred_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (CheckConstraint("role IN ('owner', 'operator', 'reviewer', 'analyst')", name="ck_admin_users_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str | None] = mapped_column(ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[str] = mapped_column(String(4000), nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
