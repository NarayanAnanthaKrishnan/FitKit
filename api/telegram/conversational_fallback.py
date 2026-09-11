"""Natural, deterministic replies used when external interpretation is unavailable."""
import re

_MUSCLES = (
    "back", "biceps", "triceps", "chest", "shoulders", "legs", "quads",
    "hamstrings", "glutes", "calves", "core", "arms",
)


def fallback_reply(text: str) -> str:
    normalized = " ".join(text.lower().split())
    mentioned = [name for name in _MUSCLES if re.search(rf"\b{re.escape(name)}\b", normalized)]
    has_workout_numbers = bool(re.search(r"\d", normalized))
    if mentioned and not has_workout_numbers:
        focus = " and ".join(mentioned[:2])
        return f"Got it—today is {focus}. Are you planning the session, or logging a workout you already did?"
    if re.fullmatch(r"(hi|hello|hey|hey there|good (morning|afternoon|evening))[!. ]*", normalized):
        return "Hey! What are you training today, or what would you like help with?"
    return "I'm having trouble understanding free text right now. Try again in a moment, or tell me a complete action such as ‘I did bench press, 3 sets of 8 at 80 kg.’"
