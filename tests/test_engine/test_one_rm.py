import pytest
from engine.one_rm import epley_1rm, MAX_EFFECTIVE_REPS


class TestEpley1RM:
    def test_reps_1_returns_weight(self):
        assert epley_1rm(100, 1) == round(100 * (1 + 1 / 30), 2)

    def test_reps_10_typical(self):
        result = epley_1rm(100, 10)
        assert result == pytest.approx(133.33, rel=1e-2)

    def test_reps_above_max_effective_is_capped(self):
        result_15 = epley_1rm(100, 15)
        result_12 = epley_1rm(100, 12)
        assert result_15 == result_12

    def test_reps_0_raises(self):
        with pytest.raises(ValueError, match="reps"):
            epley_1rm(100, 0)

    def test_negative_weight_raises(self):
        with pytest.raises(ValueError, match="weight_kg"):
            epley_1rm(-10, 5)

    def test_zero_weight_is_valid(self):
        assert epley_1rm(0, 5) == 0.0

    def test_rounding_to_2_decimals(self):
        result = epley_1rm(80, 7)
        assert result == round(80 * (1 + 7 / 30), 2)
