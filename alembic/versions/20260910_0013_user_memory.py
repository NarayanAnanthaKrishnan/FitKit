"""Add explicit encrypted user preference memory.

Revision ID: 20260910_0013
Revises: 20260910_0012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260910_0013"
down_revision = "20260910_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(30), nullable=False, server_default="preference"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_user_memory_fingerprint"),
    )
    op.create_index("ix_user_memories_user_updated", "user_memories", ["user_id", "updated_at"])


def downgrade():
    op.drop_index("ix_user_memories_user_updated", table_name="user_memories")
    op.drop_table("user_memories")
