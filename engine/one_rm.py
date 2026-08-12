"""Estimated one-rep-max via the Epley formula.

The formula degrades in accuracy above ~12 reps (it was derived from lower-rep
sets), so we cap the effective rep count used in the calculation rather than
let it silently produce a nonsense number for high-rep sets.
"""

MAX_EFFECTIVE_REPS = 12


def epley_1rm(weight_kg: float, reps: int) -> float:
    if reps < 1:
        raise ValueError("reps must be >= 1")
    if weight_kg < 0:
        raise ValueError("weight_kg must be >= 0")

    effective_reps = min(reps, MAX_EFFECTIVE_REPS)
    return round(weight_kg * (1 + effective_reps / 30), 2)
