"""payments.api_key_id: which API key submitted the request

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04 10:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('api_key_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_payments_api_key_id'), ['api_key_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_api_key_id'))
        batch_op.drop_column('api_key_id')
