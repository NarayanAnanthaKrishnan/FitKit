"""Intent-specific extraction schemas; these candidates never authorize a write."""
from datetime import date as Date
from typing import Literal
import json
import re

from pydantic import Field, StrictInt, model_validator
from api.commands import Command, GoalCommand, WeightCommand

WeightPayload = WeightCommand


class WorkoutSetPayload(Command):
    exercise_query: str = Field(min_length=2, max_length=100)
    sets: StrictInt = Field(ge=1, le=30)
    reps: StrictInt = Field(ge=1, le=100)
    weight_kg: float = Field(ge=0, le=1000)
    rpe: StrictInt | None = Field(default=None, ge=1, le=10)


class WorkoutPayload(Command):
    sets: list[WorkoutSetPayload] = Field(min_length=1, max_length=20)
    date: Date | None = None


class ProfilePayload(Command):
    field: Literal["age", "sex", "resting_hr", "max_hr", "calibration"]
    value: str


class QueryPayload(Command):
    exercise_query: str = Field(min_length=2, max_length=100)


class SessionFocusPayload(Command):
    focus: str = Field(min_length=2, max_length=80)


class RoutineReviewPayload(Command):
    exercise_queries: list[str] = Field(min_length=1, max_length=8)
    equipment: str | None = Field(default=None, min_length=2, max_length=50)


class GuidancePayload(Command):
    topic: Literal["warmup", "mobility", "recovery", "general"]


InterpretationIntent = Literal[
    "record_weight", "log_workout", "create_goal", "update_profile",
    "query_progress", "query_health", "query_recommendation", "query_today",
    "session_focus", "routine_review", "query_guidance",
    "conversation", "help", "unknown", "unsafe",
]
PAYLOADS = {"record_weight": WeightPayload, "log_workout": WorkoutPayload,
            "create_goal": GoalCommand, "update_profile": ProfilePayload,
            "query_recommendation": QueryPayload,
            "session_focus": SessionFocusPayload,
            "routine_review": RoutineReviewPayload,
            "query_guidance": GuidancePayload}


class LLMInterpretation(Command):
    intent: InterpretationIntent
    confidence: float = Field(ge=0, le=1)
    payload: dict | None = None
    clarification: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_payload(self):
        model = PAYLOADS.get(self.intent)
        if model is not None:
            raw = self.payload
            # Accept the earlier single-exercise envelope during migration.
            if self.intent == "log_workout" and isinstance(raw, dict) and "exercise_query" in raw:
                raw = {"sets": [raw]}
            self.payload = model.model_validate(raw).model_dump(mode="json")
        elif self.payload not in (None, {}):
            raise ValueError("This intent does not accept a payload")
        if self.intent == "conversation" and not self.clarification:
            raise ValueError("Conversation intent requires a reply")
        if self.clarification and re.search(r"\b(groq|grok|gpt-oss|openai|backend|language model)\b", self.clarification, re.I):
            raise ValueError("Provider details are not valid user-facing content")
        return self


def strict_schema() -> dict:
    """Keep the provider contract small; validate typed payloads locally."""
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(InterpretationIntent.__args__)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "payload_json": {"type": ["string", "null"], "maxLength": 6000},
            "reply": {"type": ["string", "null"], "maxLength": 500},
        },
        "required": ["intent", "confidence", "payload_json", "reply"],
        "additionalProperties": False,
    }


def interpretation_from_provider(value: dict) -> LLMInterpretation:
    """Decode the compact provider envelope and validate the typed candidate."""
    if "payload_json" not in value and "reply" not in value:
        return LLMInterpretation.model_validate(value)
    if set(value) != {"intent", "confidence", "payload_json", "reply"}:
        raise ValueError("Unexpected provider response fields")
    raw = value["payload_json"]
    if raw is not None and not isinstance(raw, str):
        raise ValueError("payload_json must be a JSON string or null")
    payload = json.loads(raw) if raw is not None else None
    return LLMInterpretation.model_validate({
        "intent": value["intent"], "confidence": value["confidence"],
        "payload": payload, "clarification": value["reply"],
    })
