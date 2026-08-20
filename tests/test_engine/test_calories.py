import pytest
from engine.calories import UserProfile, keytel_calories


MALE = UserProfile(weight_kg=80, age=30, sex="male", resting_hr=60, max_hr=190)
FEMALE = UserProfile(weight_kg=60, age=30, sex="female", resting_hr=65, max_hr=185)


class TestKeytelCalories:
    def test_male_returns_positive_value(self):
        cal = keytel_calories(MALE, avg_hr=140, duration_min=45)
        assert cal > 0

    def test_female_returns_positive_value(self):
        cal = keytel_calories(FEMALE, avg_hr=140, duration_min=45)
        assert cal > 0

    def test_zero_duration_returns_zero(self):
        cal = keytel_calories(MALE, avg_hr=140, duration_min=0)
        assert cal == 0.0

    def test_negative_duration_raises(self):
        with pytest.raises(ValueError, match="duration_min"):
            keytel_calories(MALE, avg_hr=140, duration_min=-10)

    def test_non_positive_hr_raises(self):
        with pytest.raises(ValueError, match="avg_hr"):
            keytel_calories(MALE, avg_hr=0, duration_min=30)

    def test_hr_exceeds_max_hr_raises(self):
        with pytest.raises(ValueError, match="avg_hr"):
            keytel_calories(MALE, avg_hr=200, duration_min=30)

    def test_no_max_hr_skips_validation(self):
        profile = UserProfile(weight_kg=80, age=30, sex="male", resting_hr=60)
        cal = keytel_calories(profile, avg_hr=200, duration_min=30)
        assert cal > 0

    def test_calibration_factor_scales_result(self):
        cal_1x = keytel_calories(MALE, avg_hr=140, duration_min=30)
        profile_1_5x = UserProfile(
            weight_kg=80, age=30, sex="male", resting_hr=60,
            max_hr=190, personal_calibration_factor=1.5,
        )
        cal_1_5x = keytel_calories(profile_1_5x, avg_hr=140, duration_min=30)
        assert cal_1_5x == pytest.approx(cal_1x * 1.5, rel=0.01)

    def test_low_hr_is_floored_at_zero(self):
        profile = UserProfile(weight_kg=80, age=30, sex="male", resting_hr=60)
        cal = keytel_calories(profile, avg_hr=1, duration_min=30)
        assert cal >= 0
