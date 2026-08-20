from datetime import date, timedelta

import pytest

from engine.overload import SessionLog, SetLog


@pytest.fixture
def today():
    return date(2026, 7, 25)


@pytest.fixture
def sample_session():
    def make(session_date: date, reps: int, weight: float, rpe: int) -> SessionLog:
        return SessionLog(
            session_date=session_date,
            sets=[SetLog(reps=reps, weight_kg=weight, rpe=rpe)],
        )
    return make


@pytest.fixture
def sample_volume():
    def make(start: date, days: int, base_volume: float = 10000.0):
        return {
            start - timedelta(days=i): base_volume * (1 + (i % 3) * 0.1)
            for i in range(days)
        }
    return make
