import re
from api.commands import TargetCommand
from api.services.workout_service import resolve_exercise
from api.telegram.agent_actions import record_agent_action
from api.telegram.client import send_telegram_message
from api.telegram.formatting import exercise_clarification
from api.telegram.keyboards import confirm_cancel_keyboard
from api.telegram.tokens import new_token


async def handle_target(db, user, chat_id, text):
    match = re.fullmatch(r"/target\s+(.+?)\s+(\d+)\s+reps(?:\s+increment\s+(\d+(?:\.\d+)?)\s+(kg|lb))?", text, re.I)
    if not match:
        await send_telegram_message(chat_id, "Usage: /target bench press 8 reps increment 2.5 kg\nThe load increment is optional; numeric increases require one.")
        return
    query, reps, increment, unit = match.groups()
    canonical, candidates = await resolve_exercise(db, query)
    if canonical is None:
        await send_telegram_message(chat_id, exercise_clarification(query, candidates))
        return
    value = float(increment) * (0.45359237 if unit and unit.lower() == "lb" else 1) if increment else None
    command = TargetCommand(exercise_name=canonical, target_reps=int(reps), load_increment_kg=value)
    token = new_token()
    await record_agent_action(db, user.id, "set_target", command.model_dump(), confirmation_token=token)
    suffix = f", increase by {value:.2f} kg when eligible" if value is not None else ", no numeric load increment"
    await send_telegram_message(chat_id, f"Target for {canonical}: {reps} reps{suffix}. Save?", reply_markup=confirm_cancel_keyboard(token))
