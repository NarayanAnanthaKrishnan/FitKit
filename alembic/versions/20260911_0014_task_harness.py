"""Order conversation turns and add content-free task telemetry.

Revision ID: 20260911_0014
Revises: 20260910_0013
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260911_0014"
down_revision = "20260910_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_turns",
        sa.Column("turn_index", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    # Existing pairs share a database timestamp. Role identifies their position.
    op.execute("UPDATE conversation_turns SET turn_index = 1 WHERE role = 'assistant'")
    op.create_check_constraint(
        "ck_conversation_turn_index", "conversation_turns", "turn_index IN (0, 1)"
    )
    op.add_column(
        "interaction_events",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "interaction_events",
        sa.Column("task_stage", sa.String(30), nullable=True),
    )
    op.create_index(
        "ix_interaction_events_task",
        "interaction_events",
        ["task_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_interaction_events_task", table_name="interaction_events")
    op.drop_column("interaction_events", "task_stage")
    op.drop_column("interaction_events", "task_id")
    op.drop_constraint(
        "ck_conversation_turn_index", "conversation_turns", type_="check"
    )
    op.drop_column("conversation_turns", "turn_index")
