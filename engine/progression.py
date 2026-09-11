"""Numeric progression only for comparable externally loaded primary sets."""
from engine.overload import OverloadDecision, _primary_set


def suggested_load(history, decision, increment):
    if decision != OverloadDecision.INCREASE_LOAD or increment is None or increment <= 0 or len(history) < 3:
        return None
    primary = [_primary_set(session.sets) for session in history[-3:]]
    if any(s is None or s.weight_kg <= 0 for s in primary):
        return None
    if len({s.weight_kg for s in primary}) != 1:
        return None
    return round(primary[-1].weight_kg + increment, 2)
