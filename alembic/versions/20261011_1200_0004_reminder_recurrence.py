"""reminder recurrence

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reminders', sa.Column('recurrence', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reminders') as batch_op:
        batch_op.drop_column('recurrence')
