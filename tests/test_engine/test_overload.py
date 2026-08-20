from datetime import date, timedelta

import pytest
from engine.overload import (
    OverloadDecision,
    SessionLog,
    SetLog,
    check_overload,
)


def make_session(days_ago: int, reps: int, weight: float, rpe: int, today: date) -> SessionLog:
    return SessionLog(
        session_date=today - timedelta(days=days_ago),
        sets=[SetLog(reps=reps, weight_kg=weight, rpe=rpe)],
    )


def make_multi_set_session(
    days_ago: int, sets: list[tuple[int, float, int]], today: date
) -> SessionLog:
    return SessionLog(
        session_date=today - timedelta(days=days_ago),
        sets=[SetLog(reps=r, weight_kg=w, rpe=rpe) for r, w, rpe in sets],
    )


TARGET_REPS = 8


class TestCheckOverload:
    def test_insufficient_data_less_than_3_sessions(self, today):
        history = [make_session(i, 8, 100, 7, today) for i in range(2)]
        assert check_overload(history, TARGET_REPS) == OverloadDecision.INSUFFICIENT_DATA

    def test_insufficient_data_empty_history(self, today):
        assert check_overload([], TARGET_REPS) == OverloadDecision.INSUFFICIENT_DATA

    def test_increase_load_when_target_hit_at_low_rpe(self, today):
        history = [make_session(i, 8, 100, 7, today) for i in range(3)]
        assert check_overload(history, TARGET_REPS) == OverloadDecision.INCREASE_LOAD

    def test_hold_when_rpe_too_high(self, today):
        history = [make_session(i, 8, 100, 8, today) for i in range(3)]
        assert check_overload(history, TARGET_REPS) == OverloadDecision.HOLD

    def test_deload_when_consecutive_high_rpe(self, today):
        history = [make_session(3, 8, 100, 6, today)] + [make_session(i, 8, 100, 9, today) for i in range(2)]
        assert check_overload(history, TARGET_REPS) == OverloadDecision.DELOAD

    def test_deload_on_exactly_2_high_rpe_sessions(self, today):
        history = [make_session(3, 8, 100, 6, today)] + [make_session(i, 8, 100, 10, today) for i in range(2)]
        assert check_overload(history, TARGET_REPS) == OverloadDecision.DELOAD

    @pytest.mark.parametrize("bad_rpe", [None])
    def test_insufficient_data_if_primary_set_rpe_missing(self, today, bad_rpe):
        sets = [SetLog(reps=8, weight_kg=100, rpe=bad_rpe)]
        history = [SessionLog(session_date=today - timedelta(days=i), sets=sets) for i in range(3)]
        assert check_overload(history, TARGET_REPS) == OverloadDecision.INSUFFICIENT_DATA

    def test_uses_primary_set_only_ignores_warmups(self, today):
        session = SessionLog(
            session_date=today - timedelta(days=1),
            sets=[
                SetLog(reps=5, weight_kg=60, rpe=6),
                SetLog(reps=8, weight_kg=100, rpe=7),
            ],
        )
        history = [session] * 3
        assert check_overload(history, TARGET_REPS) == OverloadDecision.INCREASE_LOAD

    def test_warmup_missing_rpe_does_not_block_decision(self, today):
        session = SessionLog(
            session_date=today - timedelta(days=1),
            sets=[
                SetLog(reps=5, weight_kg=60, rpe=None),
                SetLog(reps=8, weight_kg=100, rpe=7),
            ],
        )
        history = [session] * 3
        assert check_overload(history, TARGET_REPS) == OverloadDecision.INCREASE_LOAD
