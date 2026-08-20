"""Add fitness goals and agent-action audit/confirmation records.

Revision ID: 20260814_0002
Revises: 20260812_0001
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260814_0002"
down_revision: Union[str, None] = "20260812_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fitness_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("goal_type", sa.String(length=30), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agent_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confirmation_token", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_token"),
    )


def downgrade() -> None:
    op.drop_table("agent_actions")
    op.drop_table("fitness_goals")
