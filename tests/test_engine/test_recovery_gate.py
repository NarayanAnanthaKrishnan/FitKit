import pytest
from engine.recovery_gate import check_recovery


class TestCheckRecovery:
    def test_no_data_returns_none(self):
        assert check_recovery([], None, []) is None

    def test_hrv_trend_triggers_override(self):
        result = check_recovery(
            hrv_readings=[38.0, 40.0, 37.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[8.0, 7.5, 8.0],
        )
        assert result == "cap_intensity_hrv_trend"

    def test_hrv_trend_single_day_does_not_trigger(self):
        result = check_recovery(
            hrv_readings=[40.0, 50.0, 50.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[8.0, 8.0, 8.0],
        )
        assert result is None

    def test_low_sleep_trend_triggers_override(self):
        result = check_recovery(
            hrv_readings=[50.0, 50.0, 50.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[5.0, 5.5, 8.0],
        )
        assert result == "cap_intensity_sleep_trend"

    def test_low_sleep_single_night_does_not_trigger(self):
        result = check_recovery(
            hrv_readings=[50.0, 50.0, 50.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[5.0, 8.0, 8.0],
        )
        assert result is None

    def test_hrv_wins_over_sleep_when_both_trend_bad(self):
        result = check_recovery(
            hrv_readings=[38.0, 38.0, 38.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[5.0, 5.0, 5.0],
        )
        assert result == "cap_intensity_hrv_trend"

    def test_hrv_baseline_zero_does_not_raise(self):
        result = check_recovery(
            hrv_readings=[30.0, 30.0, 30.0],
            hrv_baseline_7day=0.0,
            sleep_readings=[8.0, 8.0, 8.0],
        )
        assert result is None

    def test_severe_hrv_drop_triggers_immediately(self):
        result = check_recovery(
            hrv_readings=[30.0, 50.0, 50.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[8.0, 8.0, 8.0],
        )
        assert result == "cap_intensity_severe_hrv_drop"

    def test_severe_sleep_triggers_immediately(self):
        result = check_recovery(
            hrv_readings=[50.0, 50.0, 50.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[3.5, 8.0, 8.0],
        )
        assert result == "cap_intensity_severe_sleep_deprivation"

    def test_severe_hrv_beats_severe_sleep(self):
        result = check_recovery(
            hrv_readings=[30.0, 50.0, 50.0],
            hrv_baseline_7day=50.0,
            sleep_readings=[3.5, 8.0, 8.0],
        )
        assert result == "cap_intensity_severe_hrv_drop"
