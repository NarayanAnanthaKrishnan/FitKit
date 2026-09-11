import re
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import UserProfile
from api.services import recommendation_service, workout_service
from api.services.workout_parser import parse_workouts
from api.telegram.agent_actions import record_agent_action
from api.telegram.client import send_telegram_message
from api.telegram.constants import _EDIT_PROMPTS, _EDIT_REPS_RE, _EDIT_WEIGHT_RE
from api.telegram.formatting import exercise_clarification, format_recommendation, workout_preview_from_payload
from api.telegram.keyboards import field_selection_keyboard, workout_confirm_keyboard
from api.telegram.tokens import new_token
from api.services.preferences_service import local_today, get_preferences
from api.services.extraction_service import workout_date_from_text


async def handle_log(
    db: AsyncSession, user: UserProfile, chat_id: int, text: str
) -> None:
    parts = text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if not arg:
        await send_telegram_message(
            chat_id,
            "Usage: /log <exercise> <sets>x<reps> at <weight> kg [rpe <n>]\n"
            "Example: /log bench press 3x8 at 80 kg, rpe 8\n"
            "Separate multiple exercises with ';'.",
        )
        return

    today = await local_today(db, user.id)
    workout_date = workout_date_from_text(arg, today)
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:today|yesterday)\b", "", arg, flags=re.I)
    parsed_workouts, error = parse_workouts(cleaned)
    if error:
        await send_telegram_message(chat_id, error)
        return

    sets: list[dict] = []
    exercises: list[dict] = []
    for parsed in parsed_workouts:
        canonical, candidates = await workout_service.resolve_exercise(
            db, parsed.exercise_query
        )
        if canonical is None:
            await send_telegram_message(
                chat_id, exercise_clarification(parsed.exercise_query, candidates)
            )
            return

        exercise = await workout_service.get_exercise(db, canonical)
        display_name = exercise.display_name if exercise else canonical
        exercises.append({"name": canonical, "display": display_name})
        for s in parsed.sets:
            sets.append(
                {
                    "exercise_name": canonical,
                    "reps": s.reps,
                    "weight_kg": s.weight_kg,
                    "rpe": s.rpe,
                }
            )

    prefs = await get_preferences(db, user.id)
    payload = {"date": workout_date.isoformat(), "sets": sets, "exercises": exercises, "timezone": prefs.timezone, "units": prefs.units}
    token = new_token()
    await record_agent_action(
        db, user.id, "log_workout", payload, confirmation_token=token
    )
    await send_telegram_message(
        chat_id,
        workout_preview_from_payload(payload),
        reply_markup=workout_confirm_keyboard(token),
    )


async def handle_recommend(
    db: AsyncSession, user: UserProfile, chat_id: int, text: str
) -> None:
    parts = text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    if not arg:
        await send_telegram_message(chat_id, "Usage: /recommend <exercise>")
        return

    canonical, candidates = await workout_service.resolve_exercise(db, arg)
    if canonical is None:
        await send_telegram_message(
            chat_id, exercise_clarification(arg, candidates)
        )
        return

    exercise = await workout_service.get_exercise(db, canonical)
    display_name = exercise.display_name if exercise else canonical
    result = await recommendation_service.get_recommendation(db, user.id, canonical)
    await send_telegram_message(
        chat_id, format_recommendation(display_name, result, (await get_preferences(db, user.id)).units)
    )


def apply_workout_edit(
    payload: dict, field: str | None, raw: str
) -> tuple[dict, str | None]:
    updated = dict(payload)
    updated["sets"] = [dict(s) for s in payload.get("sets", [])]
    text = (raw or "").strip()
    selected = updated["sets"]
    selector = re.match(r"set\s+(\d+)\s*:\s*(.+)$", text, re.I)
    if selector:
        index = int(selector.group(1)) - 1
        if not 0 <= index < len(selected) or field == "date":
            return updated, "Choose a valid set number for weight, reps or RPE."
        selected = [selected[index]]
        text = selector.group(2)

    if field == "weight":
        match = _EDIT_WEIGHT_RE.match(text)
        if not match or not match.group(2):
            return updated, "Send the new weight, e.g. '82.5 kg' or '180 lb'."
        value = float(match.group(1))
        unit = (match.group(2) or "kg").lower()
        if unit in {"lb", "lbs", "pound", "pounds"}:
            value = round(value * 0.45359237, 2)
        if not 0 <= value <= 1000:
            return updated, "Weight must be between 0 and 1000 kg."
        for s in selected:
            s["weight_kg"] = value
        return updated, None

    if field == "reps":
        if not _EDIT_REPS_RE.match(text):
            return updated, "Send the new reps, e.g. '8' or '8, 8, 7'."
        values = [int(p) for p in re.split(r"[,\s]+", text) if p]
        if any(not 1 <= v <= 100 for v in values):
            return updated, "Reps must be between 1 and 100."
        if len(values) == 1:
            for s in selected:
                s["reps"] = values[0]
        elif len(values) == len(selected):
            for s, v in zip(selected, values):
                s["reps"] = v
        else:
            return updated, (
                f"This workout has {len(updated['sets'])} sets; send one rep count "
                f"or {len(updated['sets'])} comma-separated counts."
            )
        return updated, None

    if field == "rpe":
        if text.lower() in {"none", "-", "n/a", "na"}:
            for s in selected:
                s["rpe"] = None
            return updated, None
        try:
            value = int(text)
        except ValueError:
            return updated, "RPE must be a number 1–10, or 'none' to remove it."
        if not 1 <= value <= 10:
            return updated, "RPE must be between 1 and 10."
        for s in selected:
            s["rpe"] = value
        return updated, None

    if field == "date":
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            return updated, "Date must be YYYY-MM-DD."
        updated["date"] = parsed_date.isoformat()
        return updated, None

    return updated, f"Unknown field '{field}'."


async def handle_correct(db, user, chat_id, text):
    import uuid
    args = text.split()
    if len(args) != 2:
        await send_telegram_message(chat_id, "Usage: /correct <workout ID from /progress>. Edit the preview, then confirm the correction.")
        return
    session = await workout_service.get_workout(db, user.id, uuid.UUID(args[1]))
    if session is None:
        await send_telegram_message(chat_id, "Workout not found.")
        return
    sets = [{"exercise_name": s.exercise_name, "reps": s.reps, "weight_kg": s.weight_kg,
             "rpe": s.rpe, "rest_seconds": s.rest_seconds, "avg_heart_rate": s.avg_heart_rate} for s in session.sets]
    exercises = [{"name": name, "display": name} for name in dict.fromkeys(s["exercise_name"] for s in sets)]
    payload = {"workout_id": str(session.id), "expected_revision": session.revision, "date": session.date.isoformat(),
               "sets": sets, "exercises": exercises, "timezone": (await get_preferences(db, user.id)).timezone}
    payload["units"] = (await get_preferences(db, user.id)).units
    token = new_token()
    await record_agent_action(db, user.id, "correct_workout", payload, confirmation_token=token)
    await send_telegram_message(chat_id, "Correction — edit then confirm:\n" + workout_preview_from_payload(payload), reply_markup=workout_confirm_keyboard(token))
