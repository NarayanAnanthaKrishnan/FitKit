from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import TelegramIdentity, UserProfile
from api.telegram.agent_actions import record_agent_action
from api.telegram.client import send_telegram_message
from api.telegram.keyboards import confirm_cancel_keyboard
from api.telegram.parsing import parse_weight
from api.telegram.tokens import new_token
from datetime import datetime, timezone
from api.services.preferences_service import get_preferences
from api.services.units import format_load


async def handle_weight(
    db: AsyncSession, identity: TelegramIdentity, user: UserProfile, chat_id: int, text: str
) -> None:
    weight_kg = parse_weight(text)
    if weight_kg is None:
        await send_telegram_message(
            chat_id,
            "Please send your current weight, for example: 80 kg or 176 lb.",
        )
        return

    token = new_token()
    await record_agent_action(
        db,
        user.id,
        "record_weight",
        {"weight_kg": weight_kg, "unit": "kg", "measured_at": datetime.now(timezone.utc).isoformat()},
        confirmation_token=token,
    )
    await send_telegram_message(
        chat_id,
        f"Record your current weight as {format_load(weight_kg, (await get_preferences(db, user.id)).units, digits=2)}?",
        reply_markup=confirm_cancel_keyboard(token),
    )
