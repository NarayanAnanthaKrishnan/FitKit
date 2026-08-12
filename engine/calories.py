from dataclasses import dataclass
from typing import Literal


@dataclass
class UserProfile:
    weight_kg: float
    age: int
    sex: Literal["male", "female"]
    resting_hr: int
    max_hr: int | None = None
    personal_calibration_factor: float = 1.0


def keytel_calories(profile: UserProfile, avg_hr: float, duration_min: float) -> float:
    if duration_min < 0:
        raise ValueError("duration_min must be >= 0")
    if avg_hr <= 0:
        raise ValueError("avg_hr must be > 0")
    if profile.max_hr is not None and avg_hr > profile.max_hr:
        raise ValueError(f"avg_hr ({avg_hr}) exceeds max_hr ({profile.max_hr})")

    if profile.sex == "male":
        cal_per_min = (
            -55.0969 + 0.6309 * avg_hr + 0.1988 * profile.weight_kg + 0.2017 * profile.age
        ) / 4.184
    else:
        cal_per_min = (
            -20.4022 + 0.4472 * avg_hr - 0.1263 * profile.weight_kg + 0.074 * profile.age
        ) / 4.184

    cal_per_min = max(cal_per_min, 0)

    return round(cal_per_min * duration_min * profile.personal_calibration_factor, 1)
