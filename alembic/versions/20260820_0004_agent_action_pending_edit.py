"""Add pending_edit_field to agent_actions for inline workout edits.

Revision ID: 20260820_0004
Revises: 20260814_0003
Create Date: 2026-08-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260820_0004"
down_revision: Union[str, None] = "20260814_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_actions",
        sa.Column("pending_edit_field", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_actions", "pending_edit_field")
