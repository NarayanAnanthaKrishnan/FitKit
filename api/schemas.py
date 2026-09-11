import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from api.commands import Command, SetCommand


class SetCreate(SetCommand):
    set_number: int = Field(ge=1, le=600, strict=True)

class WorkoutCreate(Command):
    date: date
    session_feeling_energy: int | None = Field(default=None, ge=1, le=5, strict=True)
    session_feeling_soreness: list[str] = Field(default_factory=list)
    session_feeling_mood: Optional[str] = None
    sets: list[SetCreate] = Field(min_length=1, max_length=600)

    model_config = ConfigDict(from_attributes=True)


class SetResponse(BaseModel):
    id: uuid.UUID
    exercise_name: str
    set_number: int
    reps: int
    weight_kg: float
    rpe: Optional[int] = None
    rest_seconds: Optional[int] = None
    avg_heart_rate: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class WorkoutResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    date: date
    session_feeling_energy: int | None
    session_feeling_soreness: list[str]
    session_feeling_mood: Optional[str] = None
    watch_data_available: bool
    sets: list[SetResponse]

    model_config = ConfigDict(from_attributes=True)


class ExerciseHistoryResponse(BaseModel):
    session_id: uuid.UUID
    session_date: date
    sets: list[SetResponse]


class RecommendationResponse(BaseModel):
    decision: str
    acwr_ratio: float | None = None
    acwr_flag: str
    recovery_override: str | None = None
    explanation: str
    rule_version: str = "2.0"
    as_of: date | None = None
    target_reps: int | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    freshness: dict = Field(default_factory=dict)
    suggested_load_kg: float | None = None


class HealthIngestResponse(BaseModel):
    inserted: int
    skipped: int
    skipped_reasons: list[str]
    duplicates: int = 0
    batch_duplicate: bool = False


class HealthSummaryResponse(BaseModel):
    latest_hrv: float | None = None
    latest_sleep_hours: float | None = None
    latest_resting_hr: float | None = None
    hrv_baseline_7day: float | None = None
    as_of: date
    timezone: str = "UTC"
    freshness: dict = Field(default_factory=dict)


class ShortcutHealthIngest(Command):
    """Flat payload the Apple Shortcuts bridge POSTs (one value per metric).

    Any omitted metric is simply not recorded; a timestamp defaults to the
    server's current time so a simple 'log now' shortcut needs no date logic.
    """

    measured_at: Optional[datetime] = None
    hrv: Optional[float] = Field(default=None, ge=0, le=300)
    resting_hr: Optional[float] = Field(default=None, ge=0, le=250)
    sleep_hours: Optional[float] = Field(default=None, ge=0, le=24)
    batch_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
