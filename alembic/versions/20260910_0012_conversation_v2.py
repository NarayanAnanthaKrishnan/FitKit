"""Add natural-conversation state, outcome telemetry, and consented feedback.

Revision ID: 20260910_0012
Revises: 20260908_0011
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260910_0012"
down_revision = "20260908_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_turns",
        sa.Column("kind", sa.String(30), nullable=False, server_default="conversation"),
    )
    op.create_table(
        "conversation_states",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_conversation_states_expiry", "conversation_states", ["expires_at"])
    op.create_table(
        "interaction_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("route", sa.String(20), nullable=False),
        sa.Column("intent", sa.String(50), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(50), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("rating", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("rating IS NULL OR rating IN ('up', 'down')", name="ck_interaction_rating"),
    )
    op.create_index("ix_interaction_events_created", "interaction_events", ["created_at"])
    op.create_index("ix_interaction_events_route_outcome", "interaction_events", ["route", "outcome"])
    op.create_table(
        "feedback_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interaction_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interaction_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_samples_expiry", "feedback_samples", ["expires_at"])


def downgrade():
    op.drop_index("ix_feedback_samples_expiry", table_name="feedback_samples")
    op.drop_table("feedback_samples")
    op.drop_index("ix_interaction_events_route_outcome", table_name="interaction_events")
    op.drop_index("ix_interaction_events_created", table_name="interaction_events")
    op.drop_table("interaction_events")
    op.drop_index("ix_conversation_states_expiry", table_name="conversation_states")
    op.drop_table("conversation_states")
    op.drop_column("conversation_turns", "kind")
