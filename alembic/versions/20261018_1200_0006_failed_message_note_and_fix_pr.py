"""failed message note and fix_pr

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('failed_messages', sa.Column('note', sa.Text(), nullable=True))
    op.add_column('failed_messages', sa.Column('fix_pr', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('failed_messages') as batch_op:
        batch_op.drop_column('fix_pr')
        batch_op.drop_column('note')
