from datetime import date, timedelta
import logging
import pytest
from pydantic import ValidationError
from api.commands import GoalCommand, SetCommand
from api.llm.schemas import LLMInterpretation, strict_schema
from api.services.extraction_service import verify_evidence, workout_date_from_text
from api.services.preferences_service import day_bounds
from api.services.queue_service import encrypt, decrypt
from api.telegram.confirmations import is_affirmative
from engine.overload import SessionLog, SetLog
from engine.recommend import get_recommendation
from engine.progression import suggested_load


@pytest.mark.parametrize("text", ["yes, but change it to 75 kg", "okay do not save", "yesterday I trained legs", "yes please", "save it later", "sure"])
def test_ambiguous_confirmation_never_authorizes(text):
    assert not is_affirmative(text)


@pytest.mark.parametrize("payload", [
    {"goal_type": "frequency", "target_value": -3, "unit": "kg"},
    {"goal_type": "frequency", "target_value": 3.5, "unit": "per_week"},
    {"goal_type": "weight", "target_value": float("nan"), "unit": "kg"},
])
def test_invalid_goal_rejected_before_preview(payload):
    with pytest.raises(ValidationError):
        GoalCommand.model_validate(payload)
    with pytest.raises(ValidationError):
        LLMInterpretation(intent="create_goal", confidence=.99, payload=payload)


@pytest.mark.parametrize("value", [True, 1.5, "8"])
def test_reps_are_strict_integers(value):
    with pytest.raises(ValidationError):
        SetCommand(exercise_name="squat", reps=value, weight_kg=50)


def test_recovery_preserves_deload_and_missing_data():
    today = date(2026, 9, 8)
    sessions = [SessionLog(today - timedelta(days=i), [SetLog(8, 80, 9)]) for i in (6, 3, 0)]
    assert get_recommendation(sessions, 8, {}, today, sleep_readings_last_3days=[3]).decision.value == "deload"
    assert get_recommendation([], 8, {}, today, sleep_readings_last_3days=[3]).decision.value == "insufficient_data"


def test_user_date_is_preserved_and_ambiguous_dates_rejected():
    today = date(2026, 9, 8)
    assert workout_date_from_text("bench 2026-09-01", today) == date(2026, 9, 1)
    assert workout_date_from_text("bench yesterday", today) == date(2026, 9, 7)
    with pytest.raises(ValueError):
        workout_date_from_text("bench last Friday", today)


def test_dst_calendar_days_have_correct_utc_bounds():
    start, end = day_bounds(date(2026, 3, 8), "America/New_York")
    assert end - start == timedelta(hours=23)
    start, end = day_bounds(date(2026, 11, 1), "America/New_York")
    assert end - start == timedelta(hours=25)


def test_queue_payload_is_authenticated_and_not_plaintext():
    payload = {"text": "synthetic private workout", "token": "synthetic-token"}
    ciphertext = encrypt(payload)
    assert "synthetic" not in ciphertext
    assert decrypt(ciphertext) == payload
    with pytest.raises(Exception):
        decrypt(ciphertext[:-4] + "aaaa")


def test_invented_rpe_rejected_even_when_reps_match():
    with pytest.raises(ValueError):
        verify_evidence("log_workout", {"sets": [{"exercise_query": "bench", "sets": 3, "reps": 8, "weight_kg": 80, "rpe": 8}]}, "bench 3x8 at 80 kg")


def test_routine_review_exercises_must_be_present_in_current_message():
    with pytest.raises(ValueError, match="exercises must be explicit"):
        verify_evidence(
            "routine_review",
            {"exercise_queries": ["lat pulldown", "invented curl"], "equipment": None},
            "I currently do lat pulldown",
        )


def test_session_focus_must_be_present_in_current_message():
    with pytest.raises(ValueError, match="focus must be explicit"):
        verify_evidence("session_focus", {"focus": "legs"}, "Help me plan today")


def test_strict_schema_has_no_unbounded_objects():
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(strict_schema())


def test_packaged_taxonomy_matches_documented_vocabulary():
    from pathlib import Path
    from importlib.resources import files
    root = Path(__file__).resolve().parents[2]
    assert files("api").joinpath("data/exercise_taxonomy.csv").read_text() == (root / "docs/exercise_taxonomy.csv").read_text()


def test_access_logs_strip_dashboard_tokens():
    import logging
    from api.security import AccessLogFilter
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s", ("local", "GET", "/dashboard?token=synthetic-private", "HTTP/1.1", 200), None)
    assert AccessLogFilter().filter(record)
    assert "synthetic-private" not in record.getMessage()


@pytest.mark.parametrize("text", ["bench today yesterday", "bench yesterday 2026-09-08", "bench today 2026-09-01"])
def test_conflicting_workout_dates_require_clarification(text):
    with pytest.raises(ValueError):
        workout_date_from_text(text, date(2026, 9, 8))
