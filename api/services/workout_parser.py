"""Deterministic parsing of conversational workout logs.

This module is intentionally free of FastAPI, SQLAlchemy, and Telegram imports so
it can be unit-tested in isolation. It converts shorthand such as
``bench press 3x8 at 80 kg, rpe 8`` into typed candidate data, leaving omitted
fields as ``None`` rather than guessing them.
"""

import re
from dataclasses import dataclass

LB_TO_KG = 0.45359237

# Common slang/alias -> canonical taxonomy name. Resolution against the live
# taxonomy (substring/prefix matching) happens in workout_service; this map only
# handles well-known shorthand deterministically.
ALIASES: dict[str, str] = {
    "bench": "barbell_bench_press",
    "bench press": "barbell_bench_press",
    "flat bench": "barbell_bench_press",
    "bb bench": "barbell_bench_press",
    "barbell bench": "barbell_bench_press",
    "db bench": "flat_dumbbell_bench_press",
    "incline db press": "incline_dumbbell_bench_press",
    "incline db bench": "incline_dumbbell_bench_press",
    "squat": "squat",
    "back squat": "squat",
    "deadlift": "deadlift",
    "deads": "deadlift",
    "deadlifts": "deadlift",
    "ohp": "overhead_press",
    "overhead press": "overhead_press",
    "press": "overhead_press",
    "row": "barbell_row",
    "rows": "barbell_row",
    "barbell row": "barbell_row",
    "db row": "dumbbell_row",
    "pullup": "pull_up",
    "pull up": "pull_up",
    "pull ups": "pull_up",
    "chinup": "chin_up",
    "chin ups": "chin_up",
    "chin up": "chin_up",
    "lat pulldown": "lat_pulldown",
    "pulldown": "lat_pulldown",
    "bench dip": "bench_dip",
    "bench dips": "bench_dip",
    "rdl": "romanian_deadlift",
    "romanian deadlift": "romanian_deadlift",
}

_RPE_RE = re.compile(r"\brpe\s*(?:of\s*)?(\d{1,2})\b", re.IGNORECASE)
_SETS_X_REPS_RE = re.compile(r"\b(\d{1,3})\s*[x×*]\s*(\d{1,3})\b")
_WEIGHT_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:kgs?|kg|lbs?|lb)\b", re.IGNORECASE
)
_FOR_REPS_RE = re.compile(r"\bfor\s+(\d[\d,\s]*)\b", re.IGNORECASE)

_NOISE_WORDS = {"at", "for", "on", "today", "kg", "lb", "lbs", "kgs", "rpe"}


@dataclass
class ParsedSet:
    reps: int
    weight_kg: float
    rpe: int | None


@dataclass
class ParsedWorkout:
    exercise_query: str
    sets: list[ParsedSet]


def compact(value: str) -> str:
    """Lowercase and strip non-alphanumerics for tolerant name matching."""
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _clean_residual(text: str) -> str:
    tokens = re.split(r"[\s,;]+", (text or "").strip())
    kept = [t for t in tokens if t and t.lower() not in _NOISE_WORDS]
    return " ".join(kept)


def parse_workout(text: str) -> tuple[ParsedWorkout | None, str | None]:
    """Parse a workout log into typed data, or return ``(None, error)``."""
    working = (text or "").strip()
    if not working:
        return None, "Please describe a workout, e.g. 'bench press 3x8 at 80 kg, rpe 8'."

    rpe: int | None = None
    match = _RPE_RE.search(working)
    if match:
        rpe = int(match.group(1))
        if not 1 <= rpe <= 10:
            return None, "RPE must be between 1 and 10."
        working = _RPE_RE.sub(" ", working, count=1)

    sets_reps: tuple[int, int] | None = None
    match = _SETS_X_REPS_RE.search(working)
    if match:
        sets_reps = (int(match.group(1)), int(match.group(2)))
        working = _SETS_X_REPS_RE.sub(" ", working, count=1)

    entered_weight: float | None = None
    weight_kg: float | None = None
    match = _WEIGHT_RE.search(working)
    if match:
        entered_weight = float(match.group(1))
        unit = match.group(0).lower()
        weight_kg = entered_weight
        if any(u in unit for u in ("lb",)):
            weight_kg = round(entered_weight * LB_TO_KG, 2)
        working = _WEIGHT_RE.sub(" ", working, count=1)

    for_reps: list[int] | None = None
    match = _FOR_REPS_RE.search(working)
    if match:
        raw = match.group(1)
        reps = [int(x) for x in re.split(r"[,\s]+", raw.strip()) if x.strip()]
        if not reps:
            return None, "Could not read the rep counts."
        for_reps = reps
        working = _FOR_REPS_RE.sub(" ", working, count=1)

    exercise_query = _clean_residual(working)
    if not exercise_query:
        return None, "Could not identify the exercise."

    if weight_kg is None:
        return None, "Please include a weight, e.g. '80 kg'."
    if not 0 < weight_kg <= 1000:
        return None, "Weight must be between 0 and 1000 kg."

    if sets_reps is None and for_reps is None:
        return None, "Please include sets and reps, e.g. '3x8' or 'for 5, 5, 4'."

    sets: list[ParsedSet] = []
    if sets_reps is not None:
        sets_count, reps = sets_reps
        if not 1 <= reps <= 100:
            return None, "Reps must be between 1 and 100."
        if not 1 <= sets_count <= 30:
            return None, "Set count must be between 1 and 30."
        sets = [ParsedSet(reps=reps, weight_kg=weight_kg, rpe=rpe) for _ in range(sets_count)]
    else:
        for reps in for_reps:
            if not 1 <= reps <= 100:
                return None, "Reps must be between 1 and 100."
            sets.append(ParsedSet(reps=reps, weight_kg=weight_kg, rpe=rpe))

    return ParsedWorkout(exercise_query=exercise_query, sets=sets), None


def parse_workouts(text: str) -> tuple[list[ParsedWorkout] | None, str | None]:
    """Parse one or more exercise logs separated by ``;``.

    Returns ``(workouts, None)`` on success or ``(None, error)`` when any
    segment is invalid, so a multi-exercise log is accepted atomically rather
    than silently dropping part of it.
    """
    working = (text or "").strip()
    if not working:
        return None, "Please describe a workout, e.g. 'bench press 3x8 at 80 kg, rpe 8'."

    segments = [s.strip() for s in working.split(";") if s.strip()]
    workouts: list[ParsedWorkout] = []
    for segment in segments:
        parsed, error = parse_workout(segment)
        if error:
            return None, error
        assert parsed is not None
        workouts.append(parsed)
    return workouts, None
