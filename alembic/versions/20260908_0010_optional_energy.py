"""Preserve missing session energy rather than inventing a score.

Revision ID: 20260908_0010
Revises: 20260908_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20260908_0010"
down_revision = "20260908_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("workout_sessions", "session_feeling_energy", existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Older code cannot represent missing energy. Do not silently fabricate
    # measurements or delete workouts just to make a downgrade pass.
    missing = op.get_bind().scalar(sa.text("SELECT count(*) FROM workout_sessions WHERE session_feeling_energy IS NULL"))
    if missing:
        raise RuntimeError("Downgrade requires resolving workouts with missing energy; use the pre-upgrade backup")
    op.alter_column("workout_sessions", "session_feeling_energy", existing_type=sa.Integer(), nullable=False)
