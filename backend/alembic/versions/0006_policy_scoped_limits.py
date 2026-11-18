"""policies: optional daily limits per category and per merchant

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-18 10:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_limits', JSONType, nullable=True))
        batch_op.add_column(sa.Column('merchant_limits', JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.drop_column('merchant_limits')
        batch_op.drop_column('category_limits')
