from api.services.workout_parser import parse_workout


def _parse(text):
    result, error = parse_workout(text)
    return result, error


def test_parses_sets_x_reps_with_rpe():
    result, error = _parse("bench press 3x8 at 80 kg, rpe 8")
    assert error is None
    assert result.exercise_query == "bench press"
    assert len(result.sets) == 3
    assert all(s.reps == 8 and s.weight_kg == 80.0 and s.rpe == 8 for s in result.sets)


def test_parses_for_reps_list_without_rpe():
    result, error = _parse("squat 100 kg for 5, 5, 4")
    assert error is None
    assert result.exercise_query == "squat"
    assert [s.reps for s in result.sets] == [5, 5, 4]
    assert all(s.rpe is None for s in result.sets)


def test_converts_lb_to_kg():
    result, error = _parse("bench press 3x5 at 225 lb")
    assert error is None
    assert all(s.weight_kg == round(225 * 0.45359237, 2) for s in result.sets)


def test_missing_weight_is_an_error():
    result, error = _parse("bench press 3x8 rpe 8")
    assert result is None
    assert "weight" in error


def test_missing_sets_reps_is_an_error():
    result, error = _parse("bench press 80 kg")
    assert result is None
    assert "sets and reps" in error


def test_out_of_range_reps_is_an_error():
    result, error = _parse("bench press 3x0 at 80 kg")
    assert result is None
    assert "Reps" in error


def test_out_of_range_rpe_is_an_error():
    result, error = _parse("bench press 3x8 at 80 kg, rpe 11")
    assert result is None
    assert "RPE" in error
