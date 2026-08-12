from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass
class DatedSet:
    session_date: date
    reps: int
    weight_kg: float


def compute_daily_volume(sets: list[DatedSet]) -> dict[date, float]:
    daily: dict[date, float] = defaultdict(float)
    for s in sets:
        daily[s.session_date] += s.reps * s.weight_kg
    return dict(daily)