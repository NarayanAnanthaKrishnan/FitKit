from dataclasses import dataclass
from datetime import date
from enum import Enum


class OverloadDecision(str, Enum):
    INSUFFICIENT_DATA = "insufficient_data"
    INCREASE_LOAD = "increase_load"
    HOLD = "hold"
    DELOAD = "deload"


@dataclass
class SetLog:
    reps: int
    weight_kg: float
    rpe: int | None


@dataclass
class SessionLog:
    session_date: date
    sets: list[SetLog]


MIN_SESSIONS_FOR_DECISION = 3
LOW_RPE_THRESHOLD = 7
HIGH_RPE_THRESHOLD = 9
HIGH_RPE_SESSIONS_FOR_DELOAD = 2


def _primary_set(sets: list[SetLog]) -> SetLog | None:
    if not sets:
        return None
    max_weight = max(s.weight_kg for s in sets)
    for s in sets:
        if s.weight_kg == max_weight:
            return s
    return sets[0]


def _has_missing_rpe(sets: list[SetLog]) -> bool:
    primary = _primary_set(sets)
    return primary is None or primary.rpe is None


def _all_sessions_have_primary_rpe(sessions: list[SessionLog]) -> bool:
    return not any(_has_missing_rpe(s.sets) for s in sessions)


def check_overload(history: list[SessionLog], target_reps: int) -> OverloadDecision:
    if len(history) < MIN_SESSIONS_FOR_DECISION:
        return OverloadDecision.INSUFFICIENT_DATA

    recent = history[-MIN_SESSIONS_FOR_DECISION:]
    if not _all_sessions_have_primary_rpe(recent):
        return OverloadDecision.INSUFFICIENT_DATA

    hit_target_at_low_rpe = all(
        _primary_set(s.sets).reps >= target_reps
        and _primary_set(s.sets).rpe <= LOW_RPE_THRESHOLD
        for s in recent
    )
    if hit_target_at_low_rpe:
        return OverloadDecision.INCREASE_LOAD

    last_n = history[-HIGH_RPE_SESSIONS_FOR_DELOAD:]
    if not _all_sessions_have_primary_rpe(last_n):
        return OverloadDecision.HOLD

    grinding_every_session = all(
        _primary_set(s.sets).rpe >= HIGH_RPE_THRESHOLD
        for s in last_n
    )
    if grinding_every_session:
        return OverloadDecision.DELOAD

    return OverloadDecision.HOLD
