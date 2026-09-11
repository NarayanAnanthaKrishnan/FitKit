from api.services.telegram_client import build_inline_keyboard
from api.telegram.constants import (
    _CANCEL_PREFIX,
    _CONFIRM_PREFIX,
    _EDIT_FIELD_PREFIX,
    _EDIT_FIELDS,
    _EDIT_PREFIX,
)


def confirm_cancel_keyboard(token: str, confirm_label: str = "Save") -> dict:
    return build_inline_keyboard(
        [[(confirm_label, f"{_CONFIRM_PREFIX}{token}"), ("Cancel", f"{_CANCEL_PREFIX}{token}")]]
    )


def workout_confirm_keyboard(token: str) -> dict:
    return build_inline_keyboard(
        [[
            ("Save", f"{_CONFIRM_PREFIX}{token}"),
            ("Edit", f"{_EDIT_PREFIX}{token}"),
            ("Cancel", f"{_CANCEL_PREFIX}{token}"),
        ]]
    )


def field_selection_keyboard(token: str) -> dict:
    rows = [
        [
            (label, f"{_EDIT_FIELD_PREFIX}{token}:{field}")
            for label, field in _EDIT_FIELDS[:2]
        ],
        [
            (label, f"{_EDIT_FIELD_PREFIX}{token}:{field}")
            for label, field in _EDIT_FIELDS[2:]
        ],
        [("Cancel", f"{_CANCEL_PREFIX}{token}")],
    ]
    return build_inline_keyboard(rows)


def onboarding_keyboard(*, offer_ai: bool = False) -> dict:
    rows = [[("Skip for now", "setup:skip")]]
    if offer_ai:
        rows.append([("Enable flexible chat", "setup:ai")])
    return build_inline_keyboard(rows)


def rating_keyboard(event_id) -> dict:
    return build_inline_keyboard([[("👍", f"rate:up:{event_id}"), ("👎", f"rate:down:{event_id}")]])


def feedback_keyboard() -> dict:
    return build_inline_keyboard([[("Share for 30 days", "feedback:share"), ("Not now", "feedback:discard")]])
