from api.telegram.client import send_telegram_message


async def handle_help(chat_id: int) -> None:
    await send_telegram_message(
        chat_id,
        "Just talk to me like a gym buddy. Try:\n"
        "• ‘I did bench, 3 sets of 8 at 80 kg’\n"
        "• ‘What should I lift for bench next?’\n"
        "• ‘How am I doing?’ or ‘How's my recovery?’\n"
        "• ‘I want to train 3 times a week’\n\n"
        "I’ll show a preview before changing workout, weight, goal, or profile data. "
        "Tap Save or reply exactly ‘yes’ or ‘save’; corrections get a fresh preview.\n\n"
        "Prefer shortcuts? /log, /recommend, /profile, /goals, /today, /progress, "
        "/health, /dashboard, /preferences, /cancel, and /delete still work.",
    )
