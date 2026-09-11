"""Verify extracted mutations against the user's words; never trust model confidence alone."""
import re
from datetime import date, timedelta


def workout_date_from_text(text: str, today: date) -> date:
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    has_today = bool(re.search(r"\btoday\b", text, re.I))
    has_yesterday = bool(re.search(r"\byesterday\b", text, re.I))
    if has_today and has_yesterday:
        raise ValueError("Ambiguous date")
    if len(set(dates)) > 1:
        raise ValueError("Ambiguous date")
    if dates:
        result = date.fromisoformat(dates[0])
        if (has_today and result != today) or (has_yesterday and result != today - timedelta(days=1)):
            raise ValueError("Conflicting dates")
    elif re.search(r"\byesterday\b", text, re.I):
        result = today - timedelta(days=1)
    elif re.search(r"\b(last|ago|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b", text, re.I):
        raise ValueError("Please specify the workout date as YYYY-MM-DD")
    else:
        result = today
    if result > today:
        raise ValueError("Completed workouts cannot be in the future")
    return result


def verify_evidence(intent: str, payload: dict, text: str):
    numbers = [float(v) for v in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text)]

    def explicit(value):
        return any(abs(float(value) - n) < 0.011 for n in numbers)

    def explicit_load(value):
        weights = re.findall(r"(-?\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lbs?|pounds?)\b", text, re.I)
        return (value == 0 and "bodyweight" in text.lower()) or any(abs(value - float(v) * (0.45359237 if u.lower().startswith(("lb", "pound")) else 1)) < 0.011 for v, u in weights)

    if intent == "record_weight" and not explicit_load(payload["weight_kg"]):
        raise ValueError("Weight and unit must be explicit")
    if intent == "session_focus":
        focus = payload["focus"].casefold()
        source = text.casefold().replace("&", "and")
        if focus.replace("&", "and") not in source:
            raise ValueError("Session focus must be explicit")
    if intent == "routine_review":
        source = text.casefold()
        if any(query.casefold() not in source for query in payload["exercise_queries"]):
            raise ValueError("Routine exercises must be explicit")
        if payload.get("equipment") and payload["equipment"].casefold() not in source:
            raise ValueError("Equipment must be explicit")
    if intent == "record_weight" and (payload.get("measured_at") is not None or re.search(r"\b(yesterday|last|ago|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b|\b\d{4}-\d{2}-\d{2}\b", text, re.I)):
        raise ValueError("Historical weight needs an explicit measurement time; current-weight logging cannot infer one")
    if intent == "log_workout":
        queries = [g["exercise_query"] for g in payload["sets"]]
        for group in payload["sets"]:
            if group["exercise_query"].casefold() not in text.casefold():
                raise ValueError("Exercise must be explicit")
            start = text.casefold().find(group["exercise_query"].casefold())
            following = [text.casefold().find(q.casefold(), start + len(group["exercise_query"])) for q in queries]
            end = min((i for i in following if i >= 0), default=len(text))
            segment = text[start:end]
            # Bind quantities to this exercise; unrelated numbers elsewhere in
            # the message cannot justify a mutation.
            counts = re.findall(r"\b(\d+)\s*[x×*]\s*(\d+)\b|\b(\d+)\s+sets?\s+(?:of\s+)?(\d+)\s+reps?\b", segment, re.I)
            pairs = [(int(a or c), int(b or d)) for a, b, c, d in counts]
            weights = re.findall(r"(-?\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lbs?|pounds?)\b", segment, re.I)
            loads = [round(float(v) * (.45359237 if u.lower().startswith(("lb", "pound")) else 1), 2) for v, u in weights]
            if "bodyweight" in segment.casefold():
                loads.append(0)
            if pairs != [(group["sets"], group["reps"])] or not loads or any(abs(v - group["weight_kg"]) > .011 for v in loads):
                raise ValueError("Workout quantities must be explicit")
            rpes = re.findall(r"\brpe\s*(?:of\s*)?(\d+(?:\.\d+)?)\b", segment, re.I)
            if (group["rpe"] is None and rpes) or (group["rpe"] is not None and (not rpes or any(float(v) != group["rpe"] for v in rpes))):
                raise ValueError("RPE must match the supplied value")
    if intent == "create_goal" and not explicit(payload["target_value"]):
        raise ValueError("Goal target must be explicit")
    if intent == "create_goal":
        if payload["goal_type"] == "frequency" and not re.search(r"\b(week|times|sessions?|train|workouts?)\b", text, re.I):
            raise ValueError("Goal frequency must be explicit")
        if payload["goal_type"] == "weight":
            pairs = re.findall(r"(\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)\b", text, re.I)
            if not any(abs(float(value) - payload["target_value"]) < .011 and ("lb" if unit.lower().startswith(("lb", "pound")) else "kg") == payload["unit"] for value, unit in pairs):
                raise ValueError("Goal weight and unit must match the source")
        if payload.get("target_date") and payload["target_date"] not in text:
            raise ValueError("Goal target date must be explicit")
    if intent == "update_profile":
        labels = {"age": r"\b(age|years? old|I'm|I am)\b", "resting_hr": r"\bresting\s*(hr|heart rate)\b", "max_hr": r"\b(max|maximum)\s*(hr|heart rate)\b", "calibration": r"\bcalibration\b", "sex": r"\b(male|female)\b"}
        if not re.search(labels.get(payload["field"], r"(?!)"), text, re.I):
            raise ValueError("Profile field must be explicit")
        if payload["field"] == "sex":
            if not re.search(r"\b" + re.escape(payload["value"]) + r"\b", text, re.I):
                raise ValueError("Profile value must be explicit")
        elif not explicit(payload["value"]):
            raise ValueError("Profile value must be explicit")
