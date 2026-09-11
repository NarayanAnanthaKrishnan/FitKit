"""Validate source-backed model candidates and reuse deterministic services."""
import uuid

from api.llm.schemas import LLMInterpretation
from api.services import conversation_state_service, workout_service
from api.services.extraction_service import verify_evidence, workout_date_from_text
from api.services.preferences_service import local_today, get_preferences
from api.telegram.agent_actions import record_agent_action
from api.telegram.client import send_telegram_message
from api.telegram.formatting import exercise_clarification, workout_preview_from_payload
from api.telegram.keyboards import confirm_cancel_keyboard, workout_confirm_keyboard
from api.telegram.tokens import new_token
from api.services.units import format_load
from api.services.conversation_service import remember_exchange


async def handle_llm_interpretation(db, user, chat_id, text, interp):
    interp = LLMInterpretation.model_validate(interp.model_dump())
    if interp.confidence < 0.6:
        await send_telegram_message(chat_id, "I wasn't sure what you meant. Please clarify or use /help.")
        return True
    intent, payload = interp.intent, interp.payload or {}
    verify_evidence(intent, payload, text)
    if intent == "session_focus":
        await conversation_state_service.set_state(db, user.id, "session_focus", {
            "task_id": str(uuid.uuid4()),
            "focus": payload["focus"],
            "stage": "awaiting_mode",
        })
        await send_telegram_message(
            chat_id,
            f"Got it — {payload['focus']}. Are you planning the session or logging one you finished?",
        )
        return True
    if intent == "query_guidance":
        from api.services.guidance_service import guidance_reply

        await send_telegram_message(chat_id, guidance_reply(payload["topic"], text))
        return True
    if intent == "routine_review":
        from api.services.routine_review_service import review_exercises

        state, state_payload = await conversation_state_service.get_state(db, user.id)
        review = await review_exercises(db, user.id, payload["exercise_queries"])
        if not review["ok"]:
            await conversation_state_service.set_state(db, user.id, "routine_planning", {
                **(state_payload or {}),
                "task_id": str((state_payload or {}).get("task_id") or uuid.uuid4()),
                "focus": str((state_payload or {}).get("focus", "current routine")),
                "stage": "awaiting_exercise_clarification",
            })
            await send_telegram_message(
                chat_id,
                exercise_clarification(review["query"], review["candidates"]),
            )
            return True
        exercise_names = [item["name"] for item in review["exercises"]]
        await conversation_state_service.set_state(db, user.id, "routine_planning", {
            **(state_payload or {}),
            "task_id": str((state_payload or {}).get("task_id") or uuid.uuid4()),
            "focus": str((state_payload or {}).get("focus", "current routine")),
            "equipment": payload.get("equipment") or (state_payload or {}).get("equipment"),
            "exercise_names": exercise_names,
            "stage": "reviewed",
        })
        lines = ["I checked the exercises you listed against your recorded FitKit history:"]
        missing_labels = {
            "target_reps": "set a rep target",
            "three_exercise_sessions": "log it in three sessions",
            "primary_set_rpe": "record primary-set RPE",
        }
        units = (await get_preferences(db, user.id)).units
        for item in review["exercises"]:
            missing = [missing_labels[key] for key in item["missing_inputs"] if key in missing_labels]
            if missing:
                lines.append(f"• {item['display_name']}: needs " + ", then ".join(missing) + ".")
                continue
            detail = item["decision"].replace("_", " ")
            if item["suggested_load_kg"] is not None:
                detail += f"; next supported load {format_load(item['suggested_load_kg'], units)}"
            lines.append(f"• {item['display_name']}: {detail}.")
        lines.append("Nothing was saved or changed. Log the missing details if you want a stronger review.")
        await send_telegram_message(chat_id, "\n".join(lines))
        return True
    if intent in {"record_weight", "create_goal", "update_profile"}:
        if intent == "record_weight":
            from datetime import datetime, timezone
            # The preview is a measurement now; never replace its time at confirmation.
            payload["measured_at"] = datetime.now(timezone.utc).isoformat()
        token = new_token()
        await record_agent_action(db, user.id, intent, payload, confirmation_token=token)
        if intent == "record_weight":
            message = f"Record your current weight as {format_load(payload['weight_kg'], (await get_preferences(db, user.id)).units, digits=2)}?"
        elif intent == "create_goal":
            unit = "sessions per week" if payload["unit"] == "per_week" else payload["unit"]
            message = f"New goal: {payload['target_value']:g} {unit}" + (f" by {payload['target_date']}" if payload.get("target_date") else "") + ". Save it?"
        else:
            message = f"Update {payload['field']} to {payload['value']}?"
        await send_telegram_message(chat_id, message, reply_markup=confirm_cancel_keyboard(token))
        return True
    if intent == "log_workout":
        today = await local_today(db, user.id)
        workout_date = workout_date_from_text(text, today)
        if payload.get("date") and payload["date"] != workout_date.isoformat():
            raise ValueError("The interpreted date does not match the supplied date")
        sets, exercises = [], []
        for group in payload["sets"]:
            canonical, candidates = await workout_service.resolve_exercise(db, group["exercise_query"])
            if canonical is None:
                await send_telegram_message(chat_id, exercise_clarification(group["exercise_query"], candidates))
                return True
            exercise = await workout_service.get_exercise(db, canonical)
            if not any(e["name"] == canonical for e in exercises):
                exercises.append({"name": canonical, "display": exercise.display_name})
            sets.extend({"exercise_name": canonical, "reps": group["reps"], "weight_kg": group["weight_kg"], "rpe": group["rpe"]} for _ in range(group["sets"]))
        prefs = await get_preferences(db, user.id)
        preview = {"date": workout_date.isoformat(), "sets": sets, "exercises": exercises, "timezone": prefs.timezone, "units": prefs.units}
        token = new_token()
        await record_agent_action(db, user.id, "log_workout", preview, confirmation_token=token)
        await send_telegram_message(chat_id, workout_preview_from_payload(preview), reply_markup=workout_confirm_keyboard(token))
        return True
    from api.telegram.handlers.summaries import handle_today, handle_progress, handle_health
    queries = {"query_today": handle_today, "query_progress": handle_progress, "query_health": handle_health}
    if intent in queries:
        await queries[intent](db, user, chat_id)
        return True
    if intent == "query_recommendation":
        from api.telegram.handlers.workouts import handle_recommend
        await handle_recommend(db, user, chat_id, "/recommend " + payload["exercise_query"])
        return True
    if intent == "help":
        from api.telegram.handlers.help import handle_help
        await handle_help(chat_id)
        return True
    if intent == "conversation":
        reply = interp.clarification
        await remember_exchange(db, user.id, text, reply)
        await send_telegram_message(chat_id, reply)
        return True
    if intent in {"unknown", "unsafe"}:
        reply = "I can't help with that request." if intent == "unsafe" else (interp.clarification or "Could you clarify what you want to do?")
        if intent == "unknown":
            await remember_exchange(db, user.id, text, reply)
        await send_telegram_message(chat_id, reply)
        return True
    return False
