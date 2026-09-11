import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    BigInteger,
    Integer,
    SmallInteger,
    Index,
    CheckConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # These values are nullable while a Telegram user is completing onboarding.
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sex: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    resting_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    personal_calibration_factor: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )

    workouts: Mapped[list["WorkoutSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    health_metrics: Mapped[list["HealthMetric"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    weight_measurements: Mapped[list["WeightMeasurement"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    telegram_identity: Mapped[Optional["TelegramIdentity"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    goals: Mapped[list["FitnessGoal"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    agent_actions: Mapped[list["AgentAction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    health_pairings: Mapped[list["HealthPairing"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    dashboard_links: Mapped[list["DashboardLink"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversation_turns: Mapped[list["ConversationTurn"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversation_state: Mapped[Optional["ConversationState"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    interaction_events: Mapped[list["InteractionEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    feedback_samples: Mapped[list["FeedbackSample"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memories: Mapped[list["UserMemory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class WeightMeasurement(Base):
    __tablename__ = "weight_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="telegram")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["UserProfile"] = relationship(back_populates="weight_measurements")


class TelegramIdentity(Base):
    __tablename__ = "telegram_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False, unique=True
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True, index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    onboarding_step: Mapped[str] = mapped_column(
        String(50), nullable=False, default="awaiting_weight"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["UserProfile"] = relationship(back_populates="telegram_identity")


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    encrypted_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_token: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (Index("ix_telegram_updates_queue", "status", "available_at"),)


class ConversationTurn(Base):
    """Short-lived encrypted context for opted-in natural conversation."""
    __tablename__ = "conversation_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="conversation", server_default="conversation")
    turn_index: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    encrypted_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["UserProfile"] = relationship(back_populates="conversation_turns")
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_turn_role"),
        CheckConstraint("turn_index IN (0, 1)", name="ck_conversation_turn_index"),
        Index("ix_conversation_turns_user_created", "user_id", "created_at"),
    )


class ConversationState(Base):
    """Short-lived encrypted draft used for one focused follow-up question."""
    __tablename__ = "conversation_states"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["UserProfile"] = relationship(back_populates="conversation_state")
    __table_args__ = (Index("ix_conversation_states_expiry", "expires_at"),)


class InteractionEvent(Base):
    """Privacy-safe per-turn outcome metadata; never stores message text or values."""
    __tablename__ = "interaction_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False
    )
    update_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, unique=True)
    route: Mapped[str] = mapped_column(String(20), nullable=False)
    intent: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_stage: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["UserProfile"] = relationship(back_populates="interaction_events")
    __table_args__ = (
        CheckConstraint("rating IS NULL OR rating IN ('up', 'down')", name="ck_interaction_rating"),
        Index("ix_interaction_events_created", "created_at"),
        Index("ix_interaction_events_route_outcome", "route", "outcome"),
        Index("ix_interaction_events_task", "task_id", "created_at"),
    )


class FeedbackSample(Base):
    """An explicitly confirmed, encrypted beta-feedback note."""
    __tablename__ = "feedback_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False
    )
    interaction_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interaction_events.id", ondelete="SET NULL"), nullable=True
    )
    encrypted_content: Mapped[str] = mapped_column(Text, nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["UserProfile"] = relationship(back_populates="feedback_samples")
    __table_args__ = (Index("ix_feedback_samples_expiry", "expires_at"),)


class UserMemory(Base):
    """Explicitly confirmed, encrypted conversational preference memory."""
    __tablename__ = "user_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="preference", server_default="preference")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["UserProfile"] = relationship(back_populates="memories")
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_user_memory_fingerprint"),
        Index("ix_user_memories_user_updated", "user_id", "updated_at"),
    )


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    session_feeling_energy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    session_feeling_soreness: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    session_feeling_mood: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    watch_data_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __table_args__ = (Index("ix_workouts_user_date", "user_id", "date"),)

    user: Mapped["UserProfile"] = relationship(back_populates="workouts")
    sets: Mapped[list["ExerciseSet"]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="ExerciseSet.set_number"
    )


class ExerciseSet(Base):
    __tablename__ = "exercise_sets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_sessions.id"), nullable=False
    )
    exercise_name: Mapped[str] = mapped_column(
        String(100), ForeignKey("exercise_taxonomy.name"), nullable=False
    )
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    rpe: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rest_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_heart_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    session: Mapped["WorkoutSession"] = relationship(back_populates="sets")
    exercise: Mapped["ExerciseTaxonomy"] = relationship(lazy="joined")
    __table_args__ = (Index("ix_exercise_sets_session", "session_id"),)


class HealthMetric(Base):
    __tablename__ = "health_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="apple_watch")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "metric_type", "timestamp", "source",
            name="uq_health_metric"
        ),
    )

    user: Mapped["UserProfile"] = relationship(back_populates="health_metrics")


class FitnessGoal(Base):
    __tablename__ = "fitness_goals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    goal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["UserProfile"] = relationship(back_populates="goals")


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending_confirmation"
    )
    confirmation_token: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, unique=True
    )
    pending_edit_field: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
    # Pending confirmations expire; completed/failed actions keep their
    # audit trail. NULL means no expiry (legacy rows, terminal statuses).
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["UserProfile"] = relationship(back_populates="agent_actions")
    __table_args__ = (Index("ix_actions_user_status", "user_id", "status"),)


class DashboardLink(Base):
    __tablename__ = "dashboard_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["UserProfile"] = relationship(back_populates="dashboard_links")


class HealthPairing(Base):
    __tablename__ = "health_pairings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    # Only the SHA-256 digest of the opaque pairing token is stored; the raw
    # token is shown to the user once and never persisted or logged.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["UserProfile"] = relationship(back_populates="health_pairings")


class ExerciseTaxonomy(Base):
    __tablename__ = "exercise_taxonomy"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    muscle_group: Mapped[str] = mapped_column(String(50), nullable=False)
    equipment: Mapped[str] = mapped_column(String(50), nullable=False)


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", server_default="UTC")
    units: Mapped[str] = mapped_column(String(2), default="kg", server_default="kg")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("units IN ('kg', 'lb')", name="ck_preferences_units"),)


class ExerciseTarget(Base):
    __tablename__ = "exercise_targets"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True)
    exercise_name: Mapped[str] = mapped_column(String(100), ForeignKey("exercise_taxonomy.name"), primary_key=True)
    target_reps: Mapped[int] = mapped_column(Integer)
    load_increment_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    __table_args__ = (
        CheckConstraint("target_reps BETWEEN 1 AND 100", name="ck_target_reps"),
        CheckConstraint("load_increment_kg > 0 AND load_increment_kg <= 100", name="ck_target_increment"),
    )


class DeliveryJob(Base):
    __tablename__ = "delivery_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=True)
    update_id: Mapped[int] = mapped_column(BigInteger)
    sequence: Mapped[int] = mapped_column(Integer)
    encrypted_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_token: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    __table_args__ = (
        UniqueConstraint("update_id", "sequence", name="uq_delivery_update_sequence"),
        Index("ix_delivery_queue", "status", "available_at"),
    )


class IngestBatch(Base):
    __tablename__ = "ingest_batches"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE"), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMUsage(Base):
    __tablename__ = "llm_usage"
    # NULL/global usage is deliberately stored separately from user-owned data.
    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
