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


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    session_feeling_energy: Mapped[int] = mapped_column(Integer, nullable=False)
    session_feeling_soreness: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    session_feeling_mood: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    watch_data_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

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
