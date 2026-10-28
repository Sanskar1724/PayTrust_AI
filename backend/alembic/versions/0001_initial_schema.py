"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-28 20:21:31.643891
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('agents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('callback_url', sa.String(length=500), nullable=True),
    sa.Column('webhook_secret', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('arena_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('scenario', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('stats', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_by', sa.String(length=254), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('audit_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.String(length=254), nullable=False),
    sa.Column('event_type', sa.String(length=48), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_request_id'), ['request_id'], unique=False)

    op.create_table('merchants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=True),
    sa.Column('risk_tier', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('operators',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('password_hash', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_operators_email'), ['email'], unique=True)

    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('body_hash', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('merchant_id', sa.Integer(), nullable=False),
    sa.Column('merchant_name', sa.String(length=160), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('agent_reason', sa.Text(), nullable=True),
    sa.Column('callback_url', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('decision', sa.String(length=10), nullable=False),
    sa.Column('risk_score', sa.Integer(), nullable=False),
    sa.Column('risk_level', sa.String(length=10), nullable=False),
    sa.Column('reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('policy_result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('risk_result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('simulation', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('ai', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('order', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('spend_day', sa.String(length=10), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_by', sa.String(length=254), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('processing_ms', sa.Double(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('request_id')
    )
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payments_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_merchant_id'), ['merchant_id'], unique=False)
        batch_op.create_index('ix_payments_status_created', ['status', 'created_at'], unique=False)
        batch_op.create_index('ix_payments_user_day_status', ['user_id', 'spend_day', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_user_id'), ['user_id'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('external_ref', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_ref')
    )
    op.create_table('webhook_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.String(length=120), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('entity_id', sa.String(length=120), nullable=True),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )
    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prefix')
    )
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_api_keys_agent_id'), ['agent_id'], unique=False)

    op.create_table('policies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('daily_limit', sa.Integer(), nullable=False),
    sa.Column('max_transaction', sa.Integer(), nullable=False),
    sa.Column('approval_threshold', sa.Integer(), nullable=False),
    sa.Column('allowed_categories', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('blocked_categories', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('allowed_merchants', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('blocked_merchants', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.String(length=254), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'agent_id', name='uq_policy_user_agent')
    )
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policies_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_policies_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policies_user_id'))
        batch_op.drop_index(batch_op.f('ix_policies_agent_id'))

    op.drop_table('policies')
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_keys_agent_id'))

    op.drop_table('api_keys')
    op.drop_table('webhook_events')
    op.drop_table('users')
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_user_id'))
        batch_op.drop_index('ix_payments_user_day_status')
        batch_op.drop_index('ix_payments_status_created')
        batch_op.drop_index(batch_op.f('ix_payments_merchant_id'))
        batch_op.drop_index(batch_op.f('ix_payments_created_at'))
        batch_op.drop_index(batch_op.f('ix_payments_agent_id'))

    op.drop_table('payments')
    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_operators_email'))

    op.drop_table('operators')
    op.drop_table('merchants')
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_request_id'))
        batch_op.drop_index(batch_op.f('ix_audit_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_audit_events_created_at'))

    op.drop_table('audit_events')
    op.drop_table('arena_runs')
    op.drop_table('agents')
