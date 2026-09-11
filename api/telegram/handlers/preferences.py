from api.services.preferences_service import get_preferences, set_preference, validate_preference
from api.services.audit_service import audit
from api.telegram.agent_actions import record_agent_action
from api.telegram.client import send_telegram_message
from api.telegram.keyboards import confirm_cancel_keyboard
from api.telegram.tokens import new_token


async def handle_preferences(db, user, chat_id, text):
    args = text.split(maxsplit=2)
    if len(args) == 1:
        prefs = await get_preferences(db, user.id)
        await send_telegram_message(chat_id, f"Timezone: {prefs.timezone}\nUnits: {prefs.units}\nFlexible AI chat: {'on' if prefs.ai_enabled else 'off'}\n\nYou can always use common natural requests locally. Say ‘turn flexible chat on’ for broader conversation, or use /preferences timezone America/New_York, /preferences units kg|lb, and /preferences ai on|off.")
        return
    if len(args) != 3:
        raise ValueError("Missing preference value")
    field, value = args[1:]
    validate_preference(field, value)
    if field == "ai" and value == "off":
        await set_preference(db, user.id, field, value)
        audit(db, user.id, "set_preference", {"field": "ai", "enabled": False})
        await send_telegram_message(chat_id, "Flexible AI chat is off, and recent conversation context has been deleted. Common natural requests and shortcuts still work.")
        return
    token = new_token()
    await record_agent_action(db, user.id, "set_preference", {"field": field, "value": value}, confirmation_token=token)
    notice = ""
    if field == "ai":
        notice = "Flexible AI chat sends your free-text messages and up to six recent conversation turns to FitKit's external language-processing service. Messages may include fitness or health details you type. Recent context is encrypted and kept for up to 24 hours. FitKit cannot save a workout, weight, goal, or profile change without your confirmation. You can turn it off any time.\n\n"
    await send_telegram_message(chat_id, notice + f"Set {field} to {value}?", reply_markup=confirm_cancel_keyboard(token))
