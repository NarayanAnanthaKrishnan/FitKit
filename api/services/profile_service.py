import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import UserProfile

# User-facing field key -> model attribute.
PROFILE_FIELD_MAP = {
    "age": "age",
    "sex": "sex",
    "resting_hr": "resting_hr",
    "max_hr": "max_hr",
    "calibration": "personal_calibration_factor",
}

_AGE_MIN, _AGE_MAX = 10, 120
_RESTING_HR_MIN, _RESTING_HR_MAX = 30, 150
_MAX_HR_MIN, _MAX_HR_MAX = 80, 240
_CALIBRATION_MIN, _CALIBRATION_MAX = 0.5, 2.0
_VALID_SEX = {"male", "female"}


async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    return await db.get(UserProfile, user_id)


def validate_profile_field(field_key: str, raw_value: str) -> tuple[object, str | None]:
    """Return (normalized_value, None) on success or (None, error) on failure.

    Never guesses or coerces an invalid value; callers must ask for
    clarification instead of writing.
    """
    if field_key == "sex":
        value = raw_value.strip().lower()
        if value not in _VALID_SEX:
            return None, "Sex must be 'male' or 'female'."
        return value, None

    if field_key == "age":
        value, err = _parse_int(raw_value)
        if err:
            return None, "Age must be a whole number."
        if not _AGE_MIN <= value <= _AGE_MAX:
            return None, f"Age must be between {_AGE_MIN} and {_AGE_MAX}."
        return value, None

    if field_key == "resting_hr":
        value, err = _parse_int(raw_value)
        if err:
            return None, "Resting heart rate must be a whole number."
        if not _RESTING_HR_MIN <= value <= _RESTING_HR_MAX:
            return None, (
                f"Resting heart rate must be between "
                f"{_RESTING_HR_MIN} and {_RESTING_HR_MAX}."
            )
        return value, None

    if field_key == "max_hr":
        value, err = _parse_int(raw_value)
        if err:
            return None, "Max heart rate must be a whole number."
        if not _MAX_HR_MIN <= value <= _MAX_HR_MAX:
            return None, (
                f"Max heart rate must be between {_MAX_HR_MIN} and {_MAX_HR_MAX}."
            )
        return value, None

    if field_key == "calibration":
        try:
            value = float(raw_value)
        except ValueError:
            return None, "Calibration factor must be a number."
        if not _CALIBRATION_MIN <= value <= _CALIBRATION_MAX:
            return None, (
                f"Calibration factor must be between "
                f"{_CALIBRATION_MIN} and {_CALIBRATION_MAX}."
            )
        return value, None

    return None, f"Unknown profile field '{field_key}'."


def apply_profile_update(user: UserProfile, field_key: str, value: object) -> None:
    """Apply an already-validated profile value to the model attribute."""
    attribute = PROFILE_FIELD_MAP[field_key]
    setattr(user, attribute, value)


def _parse_int(raw: str) -> tuple[int | None, bool]:
    try:
        return int(raw), False
    except ValueError:
        return None, True
