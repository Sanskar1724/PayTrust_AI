"""policy versions: every change to a policy's rules is kept; payments record their version

Existing policies get version 1 with a copy of their current rules.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-18 12:00:00
"""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
RULE_COLUMNS = ("user_id", "agent_id", "daily_limit", "weekly_limit", "monthly_limit", "max_transaction",
                "approval_threshold", "allowed_categories", "blocked_categories", "allowed_merchants",
                "blocked_merchants", "category_limits", "merchant_limits", "allowed_from", "allowed_until",
                "allowed_days", "is_active")
JSON_COLUMNS = {"allowed_categories", "blocked_categories", "allowed_merchants", "blocked_merchants",
                "category_limits", "merchant_limits", "allowed_days"}


def upgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('version', sa.Integer(), server_default='1', nullable=False))
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('policy_version', sa.Integer(), nullable=True))
    versions = op.create_table('policy_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('policy_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('rules', JSONType, nullable=False),
        sa.Column('updated_by', sa.String(length=254), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['policy_id'], ['policies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('policy_id', 'version', name='uq_policy_version'),
    )
    with op.batch_alter_table('policy_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policy_versions_policy_id'), ['policy_id'], unique=False)

    # Version 1 for every existing policy: a copy of its current rules.
    policies = sa.table('policies', sa.column('id'), sa.column('updated_by'),
                        *(sa.column(c, JSONType if c in JSON_COLUMNS else None) for c in RULE_COLUMNS))
    bind = op.get_bind()
    rows = bind.execute(sa.select(policies)).mappings().all()
    now = datetime.now(UTC)
    if rows:
        op.bulk_insert(versions, [
            {"policy_id": r["id"], "user_id": r["user_id"], "agent_id": r["agent_id"], "version": 1,
             "rules": {c: r[c] for c in RULE_COLUMNS}, "updated_by": r["updated_by"], "created_at": now}
            for r in rows
        ])


def downgrade() -> None:
    with op.batch_alter_table('policy_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policy_versions_policy_id'))
    op.drop_table('policy_versions')
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_column('policy_version')
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.drop_column('version')
