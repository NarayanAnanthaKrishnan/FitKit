from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import UserProfile
from api.services.profile_service import (
    PROFILE_FIELD_MAP,
    validate_profile_field,
)
from api.telegram.agent_actions import record_agent_action
from api.telegram.client import send_telegram_message
from api.telegram.constants import _PROFILE_SET_RE
from api.telegram.formatting import profile_display
from api.telegram.keyboards import confirm_cancel_keyboard
from api.telegram.tokens import new_token
from api.services.preferences_service import get_preferences


async def handle_profile(
    db: AsyncSession, user: UserProfile, chat_id: int, text: str
) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) == 1 or not parts[1].strip():
        await send_telegram_message(chat_id, profile_display(user, (await get_preferences(db, user.id)).units))
        return

    match = _PROFILE_SET_RE.match(text)
    if not match:
        await send_telegram_message(
            chat_id,
            "Usage: /profile set <field> <value>\n"
            "Fields: age, sex, resting_hr, max_hr, calibration",
        )
        return

    field_key = match.group(1).lower()
    raw = match.group(2).strip()
    if field_key not in PROFILE_FIELD_MAP:
        await send_telegram_message(
            chat_id,
            f"Unknown field '{field_key}'. "
            "Available: age, sex, resting_hr, max_hr, calibration",
        )
        return

    value, error = validate_profile_field(field_key, raw)
    if error:
        await send_telegram_message(chat_id, error)
        return

    token = new_token()
    await record_agent_action(
        db,
        user.id,
        "update_profile",
        {"field": field_key, "value": value},
        confirmation_token=token,
    )
    await send_telegram_message(
        chat_id,
        f"Update {field_key} to {value}?",
        reply_markup=confirm_cancel_keyboard(token),
    )
