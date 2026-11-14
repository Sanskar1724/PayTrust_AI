"""policies: optional weekly and monthly limits per agent

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14 11:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('weekly_limit', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('monthly_limit', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.drop_column('monthly_limit')
        batch_op.drop_column('weekly_limit')
