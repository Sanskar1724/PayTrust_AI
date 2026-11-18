"""policies: optional time windows (hours and weekdays) for when an agent may pay

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-18 11:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allowed_from', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('allowed_until', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('allowed_days', JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.drop_column('allowed_days')
        batch_op.drop_column('allowed_until')
        batch_op.drop_column('allowed_from')
