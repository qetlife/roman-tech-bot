"""Google Calendar: linked accounts and calendars; events as RRULEs, moved occurrences, sync state

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('google_accounts',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('refresh_token', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('default_calendar_id', sa.String(length=255), nullable=True),
    sa.Column('linked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_poll_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_table('google_calendars',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('calendar_id', sa.String(length=255), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('time_zone', sa.String(length=64), nullable=True),
    sa.Column('primary', sa.Boolean(), nullable=False),
    sa.Column('writable', sa.Boolean(), nullable=False),
    sa.Column('selected', sa.Boolean(), nullable=False),
    sa.Column('sync_token', sa.Text(), nullable=True),
    sa.Column('channel_id', sa.String(length=64), nullable=True),
    sa.Column('channel_resource_id', sa.String(length=255), nullable=True),
    sa.Column('channel_token', sa.String(length=64), nullable=True),
    sa.Column('channel_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('channel_id'),
    sa.UniqueConstraint('user_id', 'calendar_id', name='uq_google_calendars_user_calendar'),
    )

    with op.batch_alter_table('events') as batch_op:
        # Google's RRULEs can be longer than 64
        batch_op.alter_column('recurrence', existing_type=sa.String(length=64), type_=sa.Text(),
                              existing_nullable=True)
        batch_op.add_column(sa.Column('moved', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('external_updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('pending_push', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index('ix_events_external', ['user_id', 'external_calendar_id', 'external_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('events') as batch_op:
        batch_op.drop_index('ix_events_external')
        batch_op.drop_column('pending_push')
        batch_op.drop_column('external_updated_at')
        batch_op.drop_column('moved')
        batch_op.alter_column('recurrence', existing_type=sa.Text(), type_=sa.String(length=64),
                              existing_nullable=True)
    op.drop_table('google_calendars')
    op.drop_table('google_accounts')
