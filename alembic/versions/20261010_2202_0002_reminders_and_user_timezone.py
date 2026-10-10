"""reminders and user timezone

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10 22:02:53.270286

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('reminders',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('creator_user_id', sa.Uuid(), nullable=False),
    sa.Column('target_user_id', sa.Uuid(), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('remind_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('next_fire_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('fire_count', sa.Integer(), nullable=False),
    sa.Column('last_message_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['creator_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_reminders_status_next_fire_at', 'reminders', ['status', 'next_fire_at'], unique=False)
    op.create_index('ix_reminders_target_user_id', 'reminders', ['target_user_id'], unique=False)
    op.add_column('users', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'timezone')
    op.drop_index('ix_reminders_target_user_id', table_name='reminders')
    op.drop_index('ix_reminders_status_next_fire_at', table_name='reminders')
    op.drop_table('reminders')
