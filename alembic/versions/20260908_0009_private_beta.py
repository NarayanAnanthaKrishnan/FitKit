"""Durable delivery, preferences, targets, and ingestion/usage bookkeeping.

Revision ID: 20260908_0009
Revises: 20260822_0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260908_0009"
down_revision = "20260822_0008"
branch_labels = None
depends_on = None


def user_column(*, primary_key=False, nullable=False):
    return sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=primary_key, nullable=nullable)


def upgrade():
    op.add_column("workout_sessions", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_workouts_user_date", "workout_sessions", ["user_id", "date"])
    op.create_index("ix_exercise_sets_session", "exercise_sets", ["session_id"])
    op.create_index("ix_actions_user_status", "agent_actions", ["user_id", "status"])
    for col in (
        sa.Column("encrypted_payload", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(50)),
    ):
        op.add_column("telegram_updates", col)
    op.create_index("ix_telegram_updates_queue", "telegram_updates", ["status", "available_at"])
    # Old received rows have no resumable payload; retain their deduplication marker.
    op.execute("UPDATE telegram_updates SET status='ignored' WHERE status='received'")
    # Never activate an old confirmation indefinitely after the new release.
    op.execute("UPDATE agent_actions SET status='expired', confirmation_token=NULL, pending_edit_field=NULL WHERE status='pending_confirmation'")
    op.create_table("user_preferences", user_column(primary_key=True),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("units", sa.String(2), nullable=False, server_default="kg"),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ai_consent_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("units IN ('kg', 'lb')", name="ck_preferences_units"))
    op.create_table("exercise_targets", user_column(primary_key=True),
        sa.Column("exercise_name", sa.String(100), sa.ForeignKey("exercise_taxonomy.name"), primary_key=True),
        sa.Column("target_reps", sa.Integer(), nullable=False),
        sa.Column("load_increment_kg", sa.Float()),
        sa.CheckConstraint("target_reps BETWEEN 1 AND 100", name="ck_target_reps"),
        sa.CheckConstraint("load_increment_kg > 0 AND load_increment_kg <= 100", name="ck_target_increment"))
    op.create_table("delivery_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True), user_column(nullable=True),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("encrypted_payload", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_token", sa.String(32)), sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(50)),
        sa.UniqueConstraint("update_id", "sequence", name="uq_delivery_update_sequence"))
    op.create_index("ix_delivery_queue", "delivery_jobs", ["status", "available_at"])
    op.create_table("ingest_batches", user_column(primary_key=True),
        sa.Column("batch_id", sa.String(100), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("llm_usage", sa.Column("scope", sa.String(40), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("worker_heartbeats", sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for name in ("worker_heartbeats", "llm_usage", "ingest_batches", "delivery_jobs", "exercise_targets", "user_preferences"):
        op.drop_table(name)
    op.drop_index("ix_telegram_updates_queue", "telegram_updates")
    for name in ("error_code", "lease_until", "lease_token", "available_at", "attempts", "encrypted_payload"):
        op.drop_column("telegram_updates", name)
    op.drop_index("ix_actions_user_status", "agent_actions")
    op.drop_index("ix_exercise_sets_session", "exercise_sets")
    op.drop_index("ix_workouts_user_date", "workout_sessions")
    op.drop_column("workout_sessions", "revision")
