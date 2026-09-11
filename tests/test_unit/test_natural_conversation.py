import pytest

from api.services.workout_parser import parse_workout
from api.telegram.natural import classify_natural


@pytest.mark.parametrize(("text", "intent", "argument"), [
    ("How am I doing?", "progress", ""),
    ("How's my recovery?", "health", ""),
    ("Show my goals", "goals", ""),
    ("What should I lift for bench next?", "recommend", "bench"),
    ("I'm 31 years old", "profile_update", "age 31"),
    ("I want to train 3 times a week", "goal_add", "frequency 3 per week"),
    ("I want to weigh 75 kg by 2026-12-31", "goal_add", "weight 75 kg by 2026-12-31"),
    ("Set my target for bench press to 8 reps increment 2.5 kg", "target", "bench press 8 reps increment 2.5 kg"),
    ("Fix workout 7fdaf981-d4a8-41db-9077-31552e8847aa", "correct_workout", "7fdaf981-d4a8-41db-9077-31552e8847aa"),
    ("It's leg day today", "session_focus", "legs"),
    ("Okay if not soccer I'm hitting back biceps", "session_focus", "back and biceps"),
    ("Shoulder workout", "session_focus", "shoulders"),
    ("Planning", "session_mode", "planning"),
    ("Help me plan it", "session_mode", "planning"),
    ("I have a gym so tell me the most effective ones", "session_equipment", "gym"),
    ("Sure thanks", "acknowledgement", ""),
    ("What warmup can I do considering I did legs yesterday?", "guidance", "warmup"),
    ("What do you remember about me?", "memory_summary", ""),
    ("What was my last workout?", "today", ""),
    ("Remember that I train at home", "memory_add", "I train at home"),
    ("Forget my saved preferences", "memory_clear", ""),
    ("delete my account", "delete", ""),
    ("I did bench, 3 sets of 8 at 80 kg", "workout", "bench, 3 sets of 8 at 80 kg"),
    ("bench 3x8", "workout_missing_load", "bench 3x8"),
])
def test_high_confidence_natural_routes(text, intent, argument):
    result = classify_natural(text)
    assert result is not None
    assert result.name == intent
    assert result.argument == argument


@pytest.mark.parametrize("text", [
    "do something with bench", "make me stronger", "75", "delete maybe", "what should I do today",
])
def test_ambiguous_text_is_not_locally_mutated(text):
    result = classify_natural(text)
    assert result is None or result.name in {"today"}


def test_conversational_sets_of_reps_are_parsed_without_guessing_rpe():
    workout, error = parse_workout("bench 3 sets of 8 reps at 80 kg")
    assert error is None
    assert workout.exercise_query == "bench"
    assert len(workout.sets) == 3
    assert all(item.reps == 8 and item.weight_kg == 80 and item.rpe is None for item in workout.sets)


def test_guidance_preserves_source_text_for_provenance():
    text = "What stretching can I do considering I did legs yesterday?"
    result = classify_natural(text)
    assert result.source_text == text
