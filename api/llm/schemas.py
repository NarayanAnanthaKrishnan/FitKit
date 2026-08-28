"""Pydantic schemas for the bounded LLM gateway.

The gateway parses free text into a typed candidate that the Telegram adapter
validates and shows as a preview. No schema here causes a write; every
candidate must survive domain validation + human confirmation.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class WeightPayload(BaseModel):
    weight_kg: float = Field(ge=20, le=500)
    unit: Literal["kg"] = "kg"


class WorkoutSetPayload(BaseModel):
    exercise_query: str = Field(min_length=2, max_length=100)
    sets: int = Field(ge=1, le=30)
    reps: int = Field(ge=1, le=100)
    weight_kg: float = Field(ge=0, le=1000)
    rpe: Optional[int] = Field(default=None, ge=1, le=10)


class WorkoutPayload(BaseModel):
    sets: list[WorkoutSetPayload] = Field(min_length=1, max_length=20)
    date: Optional[str] = None  # YYYY-MM-DD if mentioned


class GoalWeightPayload(BaseModel):
    goal_type: Literal["weight"] = "weight"
    target_value: float = Field(gt=0)
    unit: Literal["kg", "lb"] = "kg"
    target_date: Optional[str] = None


class GoalFrequencyPayload(BaseModel):
    goal_type: Literal["frequency"] = "frequency"
    target_value: float = Field(gt=0)
    unit: Literal["per_week"] = "per_week"


InterpretationIntent = Literal[
    "record_weight",
    "log_workout",
    "create_goal",
    "query_progress",
    "query_health",
    "query_recommendation",
    "query_today",
    "help",
    "unknown",
    "unsafe",
]


class LLMInterpretation(BaseModel):
    """Structured output the model must produce.

    `payload` is intentionally generic — validated per intent by the caller
    before preview. Missing fields stay absent (None), never guessed.
    """

    intent: InterpretationIntent
    confidence: float = Field(ge=0, le=1)
    payload: Optional[dict] = None
    clarification: Optional[str] = None
    raw_text: Optional[str] = None
