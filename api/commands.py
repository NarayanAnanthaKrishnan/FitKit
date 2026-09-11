"""Channel-neutral validated commands; engine code does not import these schemas."""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator, field_validator


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def reject_boolean_numbers(cls, value):
        if type(value) is bool:
            raise ValueError("Boolean values are not fitness measurements")
        return value


class WeightCommand(Command):
    weight_kg: float = Field(ge=20, le=500)
    measured_at: datetime | None = None
    unit: Literal["kg"] = "kg"


class SetCommand(Command):
    exercise_name: str = Field(min_length=1, max_length=100)
    set_number: StrictInt | None = Field(default=None, ge=1, le=600)
    reps: StrictInt = Field(ge=1, le=100)
    weight_kg: float = Field(ge=0, le=1000)
    rpe: StrictInt | None = Field(default=None, ge=1, le=10)
    rest_seconds: StrictInt | None = Field(default=None, ge=0, le=3600)
    avg_heart_rate: StrictInt | None = Field(default=None, ge=1, le=250)


class WorkoutCommand(Command):
    date: date
    sets: list[SetCommand] = Field(min_length=1, max_length=600)


class GoalCommand(Command):
    goal_type: Literal["weight", "frequency"]
    target_value: float = Field(gt=0, le=1103)
    unit: Literal["kg", "lb", "per_week"]
    target_date: date | None = None

    @model_validator(mode="after")
    def validate_goal(self):
        if self.goal_type == "frequency":
            if self.unit != "per_week" or not self.target_value.is_integer() or self.target_value > 14:
                raise ValueError("Frequency must be a whole number from 1 to 14 sessions per week.")
        elif self.unit not in {"kg", "lb"} or not 20 <= self.target_value * (0.45359237 if self.unit == "lb" else 1) <= 500:
            raise ValueError("Weight goals must specify kg or lb and a target from 20 to 500 kg.")
        return self


class TargetCommand(Command):
    exercise_name: str = Field(min_length=1, max_length=100)
    target_reps: StrictInt = Field(ge=1, le=100)
    load_increment_kg: float | None = Field(default=None, gt=0, le=100)
