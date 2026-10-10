"""baseline: users table

Matches the schema created by Base.metadata.create_all() before Alembic was
introduced. Databases that already have the users table are stamped at this
revision on startup instead of running it (see db.db.init_db).

Revision ID: 0001
Revises:
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        sa.UniqueConstraint("telegram_id", name="users_telegram_id_key"),
    )


def downgrade() -> None:
    op.drop_table("users")
