"""users: optional overall budget across all of a user's agents

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14 10:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('daily_budget', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('weekly_budget', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('monthly_budget', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('monthly_budget')
        batch_op.drop_column('weekly_budget')
        batch_op.drop_column('daily_budget')
