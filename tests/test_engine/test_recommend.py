from datetime import date, timedelta

from engine.overload import OverloadDecision, SessionLog, SetLog
from engine.recommend import get_recommendation

TODAY = date(2026, 7, 25)


def session(days_ago: int, reps: int, weight: float, rpe: int) -> SessionLog:
    return SessionLog(
        session_date=TODAY - timedelta(days=days_ago),
        sets=[SetLog(reps=reps, weight_kg=weight, rpe=rpe)],
    )


def volume_filled(days: int = 28, base: float = 10000.0) -> dict[date, float]:
    return {
        TODAY - timedelta(days=i): base * (1 + (i % 3) * 0.1)
        for i in range(days)
    }


class TestGetRecommendation:
    def test_overload_increase_standalone(self):
        history = [session(i, 8, 100, 7) for i in range(3)]
        result = get_recommendation(
            exercise_history=history,
            target_reps=8,
            daily_volume=volume_filled(),
            today=TODAY,
        )
        assert result.decision == OverloadDecision.INCREASE_LOAD
        assert result.recovery_override is None

    def test_recovery_override_wins(self):
        history = [session(i, 8, 100, 7) for i in range(3)]
        result = get_recommendation(
            exercise_history=history,
            target_reps=8,
            daily_volume=volume_filled(),
            today=TODAY,
            hrv_readings_last_3days=[30.0, 30.0, 30.0],
            hrv_baseline_7day=50.0,
            sleep_readings_last_3days=[8.0, 8.0, 8.0],
        )
        assert result.decision == OverloadDecision.HOLD
        assert result.recovery_override is not None

    def test_acwr_downgrades_increase_to_hold(self):
        history = [session(i, 8, 100, 7) for i in range(3)]
        spike_volume = volume_filled(28, base=5000.0)
        for i in range(7):
            spike_volume[TODAY - timedelta(days=i)] = 50000.0
        result = get_recommendation(
            exercise_history=history,
            target_reps=8,
            daily_volume=spike_volume,
            today=TODAY,
        )
        assert result.decision == OverloadDecision.HOLD
        assert result.acwr_flag == "elevated_risk"

    def test_acwr_does_not_downgrade_deload(self):
        history = [session(3, 8, 100, 6)] + [session(i, 8, 100, 9) for i in range(2)]
        spike_volume = volume_filled(28, base=5000.0)
        for i in range(7):
            spike_volume[TODAY - timedelta(days=i)] = 50000.0
        result = get_recommendation(
            exercise_history=history,
            target_reps=8,
            daily_volume=spike_volume,
            today=TODAY,
        )
        assert result.decision == OverloadDecision.DELOAD

    def test_insufficient_data_propagates(self):
        result = get_recommendation(
            exercise_history=[],
            target_reps=8,
            daily_volume=volume_filled(),
            today=TODAY,
        )
        assert result.decision == OverloadDecision.INSUFFICIENT_DATA