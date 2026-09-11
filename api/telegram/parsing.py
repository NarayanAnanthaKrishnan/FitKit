"""Pure parsing helpers for Telegram text — no DB, no I/O."""
from __future__ import annotations

from datetime import date

from api.telegram.constants import (
    _FREQUENCY_GOAL_RE,
    _WEIGHT_GOAL_RE,
    _WEIGHT_PATTERN,
)


def parse_weight(text: str) -> float | None:
    match = _WEIGHT_PATTERN.match(text)
    if not match:
        return None
    if not match.group(2):
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "kg").lower()
    if unit in {"lb", "lbs", "pound", "pounds"}:
        value *= 0.45359237
    if not 20 <= value <= 500:
        return None
    return round(value, 2)


def command(text: str) -> str:
    return text.split(maxsplit=1)[0].lower().split("@", 1)[0]


def parse_goal_spec(arg: str) -> tuple[dict, str | None]:
    kind, _, rest = arg.partition(" ")
    kind = kind.lower()
    rest = rest.strip()

    if kind == "weight":
        match = _WEIGHT_GOAL_RE.match(rest)
        if not match:
            return {}, "Usage: /goals add weight <value> kg|lb [by YYYY-MM-DD]"
        value = float(match.group(1))
        unit = "lb" if match.group(2).lower() in {"lb", "lbs"} else "kg"
        target_date = None
        if match.group(3):
            try:
                target_date = date.fromisoformat(match.group(3))
            except ValueError:
                return {}, "Target date must be YYYY-MM-DD."
        return (
            {
                "goal_type": "weight",
                "target_value": value,
                "unit": unit,
                "target_date": target_date,
            },
            None,
        )

    if kind == "frequency":
        match = _FREQUENCY_GOAL_RE.match(rest)
        if not match:
            return {}, "Usage: /goals add frequency <sessions> per week"
        value = float(match.group(1))
        if value <= 0:
            return {}, "Frequency must be greater than zero."
        return (
            {
                "goal_type": "frequency",
                "target_value": value,
                "unit": "per_week",
                "target_date": None,
            },
            None,
        )

    return {}, "Goal type must be 'weight' or 'frequency'."


def goal_preview(spec: dict) -> str:
    if spec["goal_type"] == "weight":
        suffix = f" by {spec['target_date']}" if spec["target_date"] else ""
        return f"New goal: weight {spec['target_value']} {spec['unit']}{suffix}. Save it?"
    return f"New goal: {spec['target_value']:.0f} sessions per week. Save it?"
