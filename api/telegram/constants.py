import re

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
DEFAULT_ACTION_TTL_SECONDS = 900

_WEIGHT_PATTERN = re.compile(
    r"^\s*(?:i\s+weigh|weight\s*(?:is|:)?)?\s*"
    r"(\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)?\s*(?:today)?\s*$",
    re.IGNORECASE,
)
_PROFILE_SET_RE = re.compile(r"^/profile\s+set\s+(\S+)\s+(.+)$", re.IGNORECASE)
_WEIGHT_GOAL_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(kg|lbs?)\s*(?:by\s+(\d{4}-\d{2}-\d{2}))?\s*$",
    re.IGNORECASE,
)
_FREQUENCY_GOAL_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(?:x\s*)?(?:per\s*week|/week|sessions?\s*(?:per\s*week|/week))$",
    re.IGNORECASE,
)

_CONFIRM_PREFIX = "confirm:"
_CANCEL_PREFIX = "cancel:"
_EDIT_PREFIX = "edit:"
_EDIT_FIELD_PREFIX = "edit_field:"

_EDIT_FIELDS = [
    ("Weight", "weight"),
    ("Reps", "reps"),
    ("RPE", "rpe"),
    ("Date", "date"),
]
_EDIT_PROMPTS = {
    "weight": "Send the new weight, e.g. '82.5 kg' or '180 lb'.",
    "reps": "Send the new reps, e.g. '8' or '8, 8, 7'.",
    "rpe": "Send RPE 1–10, or 'none' to remove it.",
    "date": "Send the new date as YYYY-MM-DD.",
}
_EDIT_WEIGHT_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)?\s*$",
    re.IGNORECASE,
)
_EDIT_REPS_RE = re.compile(r"^\s*(\d[\d,\s]*)$")

_DECISION_LABELS = {
    "increase_load": "Increase load",
    "hold": "Hold",
    "deload": "Deload",
    "insufficient_data": "Not enough data yet",
}
