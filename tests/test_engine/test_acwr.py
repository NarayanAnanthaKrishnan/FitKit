from datetime import date, timedelta

import pytest
from engine.acwr import compute_acwr, acwr_flag

TODAY = date(2026, 7, 25)


def volume_dict(days: int, base: float = 10000.0):
    return {
        TODAY - timedelta(days=i): base * (1 + (i % 3) * 0.1)
        for i in range(days)
    }


class TestComputeACWR:
    def test_returns_none_when_less_than_14_days_data(self):
        assert compute_acwr(volume_dict(10), TODAY) is None

    def test_returns_none_on_zero_chronic_volume(self):
        assert compute_acwr({}, TODAY) is None

    def test_ratio_in_normal_range(self):
        ratio = compute_acwr(volume_dict(28), TODAY)
        assert ratio is not None
        assert 0.8 <= ratio <= 1.5

    def test_ratio_elevated_with_spike(self):
        vols = volume_dict(28, base=5000.0)
        for i in range(7):
            vols[TODAY - timedelta(days=i)] = 50000.0
        ratio = compute_acwr(vols, TODAY)
        assert ratio is not None
        assert ratio > 1.5

    def test_ratio_low_with_undertraining(self):
        vols = volume_dict(28, base=10000.0)
        for i in range(7):
            vols[TODAY - timedelta(days=i)] = 1000.0
        ratio = compute_acwr(vols, TODAY)
        assert ratio is not None
        assert ratio < 0.8


class TestACWRFlag:
    def test_none_ratio(self):
        assert acwr_flag(None) == "insufficient_data"

    def test_elevated_risk(self):
        assert acwr_flag(1.6) == "elevated_risk"

    def test_undertraining(self):
        assert acwr_flag(0.7) == "undertraining"

    def test_normal(self):
        assert acwr_flag(1.1) == "normal"

    def test_boundary_elevated(self):
        assert acwr_flag(1.5) == "normal"

    def test_boundary_undertraining(self):
        assert acwr_flag(0.8) == "normal"
