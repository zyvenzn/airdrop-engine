"""initial schema for users, points, farming, and tasks"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("telegram_id > 0", name="ck_users_telegram_id_positive"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "point_balances",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("available", sa.BigInteger(), nullable=False),
        sa.Column("pending", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("available >= 0", name="ck_point_balances_available_nonnegative"),
        sa.CheckConstraint("pending >= 0", name="ck_point_balances_pending_nonnegative"),
    )

    op.create_table(
        "points_ledger",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("reference_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("balance_bucket", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_points_ledger_idempotency_key"),
        sa.CheckConstraint("amount != 0", name="ck_points_ledger_amount_nonzero"),
        sa.CheckConstraint("balance_bucket IN ('available', 'pending')", name="ck_points_ledger_bucket"),
    )
    op.create_index("ix_points_ledger_user_id", "points_ledger", ["user_id"])

    op.create_table(
        "farming_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reward_points", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint("ends_at > started_at", name="ck_farming_session_positive_duration"),
        sa.CheckConstraint("status IN ('active', 'claimed', 'expired', 'cancelled')", name="ck_farming_session_status"),
        sa.CheckConstraint("reward_points > 0", name="ck_farming_reward_positive"),
    )
    op.create_index("ix_farming_sessions_user_id", "farming_sessions", ["user_id"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("verification_type", sa.String(length=32), nullable=False),
        sa.Column("reward_points", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("reward_points > 0", name="ck_tasks_reward_positive"),
        sa.CheckConstraint("status IN ('draft', 'active', 'paused', 'archived')", name="ck_tasks_status"),
    )

    op.create_table(
        "task_submissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("evidence", sa.String(length=2000), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "task_id", name="uq_task_submission_user_task"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_task_submission_status"),
    )
    op.create_index("ix_task_submissions_user_id", "task_submissions", ["user_id"])
    op.create_index("ix_task_submissions_task_id", "task_submissions", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_submissions_task_id", table_name="task_submissions")
    op.drop_index("ix_task_submissions_user_id", table_name="task_submissions")
    op.drop_table("task_submissions")
    op.drop_table("tasks")
    op.drop_index("ix_farming_sessions_user_id", table_name="farming_sessions")
    op.drop_table("farming_sessions")
    op.drop_index("ix_points_ledger_user_id", table_name="points_ledger")
    op.drop_table("points_ledger")
    op.drop_table("point_balances")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
