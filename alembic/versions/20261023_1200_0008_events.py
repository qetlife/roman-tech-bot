"""events, and reminders and failed messages linked to them

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum columns are plain VARCHAR(16), like reminders.status.
    op.create_table('events',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('all_day', sa.Boolean(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('recurrence', sa.String(length=64), nullable=True),
    sa.Column('skipped', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('request', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('external_source', sa.String(length=16), nullable=True),
    sa.Column('external_calendar_id', sa.String(length=255), nullable=True),
    sa.Column('external_id', sa.String(length=255), nullable=True),
    sa.Column('etag', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_events_user_id_status', 'events', ['user_id', 'status'], unique=False)

    with op.batch_alter_table('reminders') as batch_op:
        # "30 min before every padel" holds the event's repeat and skipped days: longer than 64.
        batch_op.alter_column('recurrence', existing_type=sa.String(length=64), type_=sa.Text(),
                              existing_nullable=True)
        batch_op.add_column(sa.Column('event_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                                      nullable=True))
        batch_op.add_column(sa.Column('event_offset', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_reminders_event_id', 'events', ['event_id'], ['id'], ondelete='SET NULL')
        batch_op.create_index('ix_reminders_event_id', ['event_id'], unique=False)

    with op.batch_alter_table('failed_messages') as batch_op:
        batch_op.add_column(sa.Column('event_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                                      nullable=True))
        batch_op.create_foreign_key('fk_failed_messages_event_id', 'events', ['event_id'], ['id'],
                                    ondelete='SET NULL')
        batch_op.create_index('ix_failed_messages_event_id', ['event_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('failed_messages') as batch_op:
        batch_op.drop_index('ix_failed_messages_event_id')
        batch_op.drop_constraint('fk_failed_messages_event_id', type_='foreignkey')
        batch_op.drop_column('event_id')
    with op.batch_alter_table('reminders') as batch_op:
        batch_op.drop_index('ix_reminders_event_id')
        batch_op.drop_constraint('fk_reminders_event_id', type_='foreignkey')
        batch_op.drop_column('event_offset')
        batch_op.drop_column('event_id')
        batch_op.alter_column('recurrence', existing_type=sa.Text(), type_=sa.String(length=64),
                              existing_nullable=True)
    op.drop_index('ix_events_user_id_status', table_name='events')
    op.drop_table('events')
