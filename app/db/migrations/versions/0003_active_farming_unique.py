"""enforce one active farming session per user"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_active_farming_unique"
down_revision: Union[str, None] = "0002_referrals_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing duplicate active sessions must be reconciled before this migration is applied.
    op.create_index(
        "uq_farming_one_active_per_user",
        "farming_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_farming_one_active_per_user", table_name="farming_sessions")
