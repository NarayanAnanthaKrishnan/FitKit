import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SetCreate(BaseModel):
    exercise_name: str
    set_number: int
    reps: int = Field(ge=1)
    weight_kg: float = Field(ge=0)
    rpe: int = Field(ge=1, le=10)
    rest_seconds: Optional[int] = None
    avg_heart_rate: Optional[int] = None


class WorkoutCreate(BaseModel):
    date: date
    session_feeling_energy: int = Field(ge=1, le=5)
    session_feeling_soreness: list[str] = Field(default_factory=list)
    session_feeling_mood: Optional[str] = None
    sets: list[SetCreate] = Field(min_length=1)

    model_config = ConfigDict(from_attributes=True)


class SetResponse(BaseModel):
    id: uuid.UUID
    exercise_name: str
    set_number: int
    reps: int
    weight_kg: float
    rpe: int
    rest_seconds: Optional[int] = None
    avg_heart_rate: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class WorkoutResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    date: date
    session_feeling_energy: int
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


class HealthIngestResponse(BaseModel):
    inserted: int
    skipped: int
    skipped_reasons: list[str]


class HealthSummaryResponse(BaseModel):
    latest_hrv: float | None = None
    latest_sleep_hours: float | None = None
    latest_resting_hr: float | None = None
    hrv_baseline_7day: float | None = None
    as_of: date
