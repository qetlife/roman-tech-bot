"""failed messages

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17 22:36:32.230646

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum columns are plain VARCHAR(16), like reminders.status.
    op.create_table('failed_messages',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.String(length=16), nullable=False),
    sa.Column('intent', sa.String(length=64), nullable=True),
    sa.Column('bot_understood', sa.JSON(), nullable=True),
    sa.Column('reminder_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('fixed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['reminder_id'], ['reminders.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_failed_messages_reminder_id', 'failed_messages', ['reminder_id'], unique=False)
    op.create_index('ix_failed_messages_status_created_at', 'failed_messages', ['status', 'created_at'], unique=False)
    op.add_column('reminders', sa.Column('request', sa.Text(), nullable=True))
    op.add_column('reminders', sa.Column('source', sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reminders') as batch_op:
        batch_op.drop_column('source')
        batch_op.drop_column('request')
    op.drop_index('ix_failed_messages_status_created_at', table_name='failed_messages')
    op.drop_index('ix_failed_messages_reminder_id', table_name='failed_messages')
    op.drop_table('failed_messages')
