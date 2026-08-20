"""Allow exercise sets to omit RPE.

Revision ID: 20260814_0003
Revises: 20260814_0002
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260814_0003"
down_revision: Union[str, None] = "20260814_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "exercise_sets",
        "rpe",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Restoring NOT NULL would fail on existing rows with NULL RPE; leave a
    # documented manual path. This migration only relaxes the constraint.
    op.alter_column(
        "exercise_sets",
        "rpe",
        existing_type=sa.Integer(),
        nullable=False,
    )
