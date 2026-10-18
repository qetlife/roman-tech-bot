"""contacts and invites

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('first_name', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('username', sa.String(length=64), nullable=True))
    op.create_index('ix_users_username', 'users', ['username'], unique=False)

    # Enum columns are plain VARCHAR(16), like reminders.status.
    op.create_table('contacts',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('contact_user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_user_id', 'contact_user_id', name='uq_contacts_owner_contact'),
    )
    op.create_index('ix_contacts_contact_user_id', 'contacts', ['contact_user_id'], unique=False)

    op.create_table('invites',
    sa.Column('token', sa.String(length=32), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('used_by_user_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['used_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('token'),
    )


def downgrade() -> None:
    op.drop_table('invites')
    op.drop_index('ix_contacts_contact_user_id', table_name='contacts')
    op.drop_table('contacts')
    op.drop_index('ix_users_username', table_name='users')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('username')
        batch_op.drop_column('first_name')
