from datetime import date

from engine.volume import DatedSet, compute_daily_volume


class TestComputeDailyVolume:
    def test_empty_list_returns_empty_dict(self):
        assert compute_daily_volume([]) == {}

    def test_single_set(self):
        sets = [DatedSet(session_date=date(2026, 7, 25), reps=10, weight_kg=100)]
        assert compute_daily_volume(sets) == {date(2026, 7, 25): 1000.0}

    def test_multiple_sets_same_day(self):
        sets = [
            DatedSet(session_date=date(2026, 7, 25), reps=10, weight_kg=100),
            DatedSet(session_date=date(2026, 7, 25), reps=8, weight_kg=80),
        ]
        assert compute_daily_volume(sets) == {date(2026, 7, 25): 1640.0}

    def test_sets_on_different_days(self):
        sets = [
            DatedSet(session_date=date(2026, 7, 25), reps=10, weight_kg=100),
            DatedSet(session_date=date(2026, 7, 24), reps=8, weight_kg=80),
        ]
        result = compute_daily_volume(sets)
        assert result == {date(2026, 7, 25): 1000.0, date(2026, 7, 24): 640.0}

    def test_bodyweight_set_contributes_zero(self):
        sets = [DatedSet(session_date=date(2026, 7, 25), reps=10, weight_kg=0)]
        assert compute_daily_volume(sets) == {date(2026, 7, 25): 0.0}

    def test_mixed_exercises_aggregated_per_day(self):
        sets = [
            DatedSet(session_date=date(2026, 7, 25), reps=5, weight_kg=100),
            DatedSet(session_date=date(2026, 7, 25), reps=8, weight_kg=60),
            DatedSet(session_date=date(2026, 7, 24), reps=10, weight_kg=50),
        ]
        result = compute_daily_volume(sets)
        assert result == {date(2026, 7, 25): 980.0, date(2026, 7, 24): 500.0}