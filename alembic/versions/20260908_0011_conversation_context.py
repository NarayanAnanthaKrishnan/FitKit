"""Add short-lived encrypted conversational context.

Revision ID: 20260908_0011
Revises: 20260908_0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260908_0011"
down_revision = "20260908_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_turn_role"),
    )
    op.create_index("ix_conversation_turns_user_created", "conversation_turns", ["user_id", "created_at"])


def downgrade():
    op.drop_index("ix_conversation_turns_user_created", table_name="conversation_turns")
    op.drop_table("conversation_turns")
