import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import AgentAction, TelegramIdentity, UserProfile
from api.services import onboarding_service, recommendation_service, workout_service
from api.services.profile_service import apply_profile_update
from api.services.goal_service import create_goal, delete_goal
from api.services.weight_service import record_weight
from api.telegram.agent_actions import not_expired, pending_action, validate_action
from api.telegram.tokens import new_token
from api.services.preferences_service import set_preference, get_preferences
from api.services.units import format_load
from api.services.target_service import set_target
from api.telegram.client import answer_callback_query, send_telegram_message
from api.telegram.constants import _EDIT_PROMPTS, _EDIT_WEIGHT_RE, _EDIT_REPS_RE
from api.telegram.formatting import workout_preview_from_payload
from api.telegram.handlers.workouts import apply_workout_edit
from api.telegram.identity import get_or_create_identity
from api.telegram.keyboards import field_selection_keyboard, workout_confirm_keyboard
from api.telegram.constants import _CANCEL_PREFIX, _CONFIRM_PREFIX, _EDIT_FIELD_PREFIX, _EDIT_PREFIX, _DECISION_LABELS


async def handle_callback(
    db: AsyncSession, callback: tuple[int, int, str, dict, str]
) -> None:
    telegram_user_id, chat_id, data, sender, callback_id = callback
    identity = await db.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == telegram_user_id))
    if identity is None:
        await answer_callback_query(callback_id, "Session not found. Send /start.")
        return
    user = await db.get(UserProfile, identity.user_id)
    if user is None:
        await answer_callback_query(callback_id, "Session not found. Send /start.")
        return

    if data.startswith("rate:"):
        parts = data.split(":", 2)
        try:
            event_id = uuid.UUID(parts[2])
        except (ValueError, IndexError):
            await answer_callback_query(callback_id, "That rating is no longer available.")
            return
        from api.services.interaction_service import rate_interaction
        if not await rate_interaction(db, user.id, event_id, parts[1]):
            await answer_callback_query(callback_id, "That rating is no longer available.")
            return
        await answer_callback_query(callback_id, "Thanks!")
        if parts[1] == "down":
            from api.services.conversation_state_service import set_state
            await set_state(db, user.id, "feedback_note", {"event_id": str(event_id)})
            await send_telegram_message(chat_id, "Want to help me improve? Reply with what felt off. I’ll show a 30-day sharing notice before anything is retained.")
    elif data == "feedback:share":
        from api.services.conversation_state_service import clear_state, get_state
        from api.services.interaction_service import save_feedback
        state, payload = await get_state(db, user.id)
        if state is None or state.kind != "feedback_review":
            await answer_callback_query(callback_id, "That feedback draft has expired.")
            return
        event_id = uuid.UUID(payload["event_id"]) if payload.get("event_id") else None
        await save_feedback(db, user.id, payload["content"], event_id)
        await clear_state(db, user.id)
        await answer_callback_query(callback_id, "Shared")
        await send_telegram_message(chat_id, "Thanks — your encrypted feedback will be deleted automatically after 30 days.")
    elif data == "feedback:discard":
        from api.services.conversation_state_service import clear_state
        await clear_state(db, user.id)
        await answer_callback_query(callback_id, "Discarded")
        await send_telegram_message(chat_id, "No problem — the feedback draft was discarded.")
    elif data == "setup:skip":
        from api.telegram.handlers.onboarding import handle_skip
        await answer_callback_query(callback_id)
        await handle_skip(db, identity, user, chat_id)
    elif data == "setup:ai":
        from api.telegram.handlers.preferences import handle_preferences
        await answer_callback_query(callback_id)
        await handle_preferences(db, user, chat_id, "/preferences ai on")
    elif data.startswith(_CONFIRM_PREFIX):
        await _confirm_action(db, user, chat_id, callback_id, data[len(_CONFIRM_PREFIX):])
    elif data.startswith(_EDIT_FIELD_PREFIX):
        await _edit_field_action(db, user, chat_id, callback_id, data[len(_EDIT_FIELD_PREFIX):])
    elif data.startswith(_EDIT_PREFIX):
        await _edit_action(db, user, chat_id, callback_id, data[len(_EDIT_PREFIX):])
    elif data.startswith(_CANCEL_PREFIX):
        await _cancel_action(db, user, chat_id, callback_id, data[len(_CANCEL_PREFIX):])
    else:
        await answer_callback_query(callback_id, "Unknown action.")


async def _confirm_action(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    callback_id: str,
    token: str,
) -> None:
    action = await pending_action(db, user.id, token)
    if action is None:
        await answer_callback_query(callback_id, "This action is no longer available.")
        return
    if action.action_type == "delete_user" or action.pending_edit_field is not None:
        await answer_callback_query(callback_id, "Complete the requested confirmation or edit first.")
        return
    action_id = action.id
    savepoint = await db.begin_nested()
    try:
        message = await _execute_action(db, user, action)
        await savepoint.commit()
    except (ValueError, KeyError, TypeError):
        await savepoint.rollback()
        failed = await db.get(AgentAction, action_id, populate_existing=True)
        failed.status = "failed"
        message = "This preview is no longer valid. Create a new preview and check the details."
    await answer_callback_query(callback_id)
    await send_telegram_message(chat_id, message)


async def _cancel_action(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    callback_id: str,
    token: str,
) -> None:
    action = await pending_action(db, user.id, token)
    if action is None:
        await answer_callback_query(callback_id, "Nothing to cancel.")
        return
    action.status = "cancelled"
    await answer_callback_query(callback_id)
    await send_telegram_message(chat_id, "Cancelled.")


async def _edit_action(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    callback_id: str,
    token: str,
) -> None:
    action = await pending_action(db, user.id, token)
    if action is None:
        await answer_callback_query(callback_id, "This action is no longer available.")
        return
    if action.action_type not in {"log_workout", "correct_workout"}:
        await answer_callback_query(callback_id, "This action can't be edited.")
        return
    await answer_callback_query(callback_id)
    await send_telegram_message(
        chat_id,
        "What would you like to change?",
        reply_markup=field_selection_keyboard(token),
    )


async def _edit_field_action(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    callback_id: str,
    spec: str,
) -> None:
    token, _, field = spec.rpartition(":")
    action = await pending_action(db, user.id, token)
    if action is None:
        await answer_callback_query(callback_id, "This action is no longer available.")
        return
    if action.action_type not in {"log_workout", "correct_workout"} or field not in _EDIT_PROMPTS:
        await answer_callback_query(callback_id, "Unknown field.")
        return
    action.pending_edit_field = field
    await answer_callback_query(callback_id)
    await send_telegram_message(chat_id, _EDIT_PROMPTS[field])


async def apply_edit_input(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    action: AgentAction,
    text: str,
) -> None:
    updated, error = apply_workout_edit(action.input_payload, action.pending_edit_field, text)
    if error:
        await send_telegram_message(chat_id, error)
        return
    try:
        await validate_action(db, user.id, action.action_type, updated)
    except (ValueError, KeyError, TypeError):
        await send_telegram_message(chat_id, "Those edits aren't valid. Check the values and date; the previous preview is unchanged.")
        return
    action.input_payload = updated
    action.pending_edit_field = None
    action.confirmation_token = new_token()
    await send_telegram_message(
        chat_id,
        workout_preview_from_payload(updated),
        reply_markup=workout_confirm_keyboard(action.confirmation_token),
    )


async def _execute_action(
    db: AsyncSession, user: UserProfile, action: AgentAction
) -> str:
    if action.status != "pending_confirmation" or action.pending_edit_field:
        return "This action is no longer available."
    await validate_action(db, user.id, action.action_type, action.input_payload)
    payload = action.input_payload

    if action.action_type == "remember_preference":
        from api.services.memory_service import save_proposal

        await save_proposal(db, user.id, payload)
        action.status, action.result_payload = "completed", {"category": "preference"}
        return "Got it — I’ll remember that preference. Say ‘what do you remember about me?’ to review it."

    if action.action_type == "clear_memories":
        from api.services.memory_service import clear_memories

        removed = await clear_memories(db, user.id)
        action.status, action.result_payload = "completed", {"removed": removed}
        return f"Cleared {removed} saved conversational preference{'s' if removed != 1 else ''}. Your structured fitness records were not changed."

    if action.action_type == "set_preference":
        await set_preference(db, user.id, payload["field"], payload["value"])
        action.status, action.result_payload = "completed", {"field": payload["field"]}
        label = "Flexible chat" if payload["field"] == "ai" else payload["field"]
        return f"Nice — {label} is updated."

    if action.action_type == "set_target":
        await set_target(db, user.id, payload)
        action.status, action.result_payload = "completed", {"exercise_name": payload["exercise_name"]}
        return "Exercise target saved. Use /recommend to check progression."

    if action.action_type == "record_weight":
        weight_kg = float(payload["weight_kg"])
        await record_weight(
            db, user.id, weight_kg, datetime.fromisoformat(payload["measured_at"]) if payload.get("measured_at") else datetime.now(timezone.utc), source="telegram"
        )
        action.result_payload = {"weight_kg": weight_kg}
        action.status = "completed"
        message = f"Saved — your current weight is {format_load(weight_kg, (await get_preferences(db, user.id)).units, digits=2)}."
        identity = await db.scalar(
            select(TelegramIdentity).where(TelegramIdentity.user_id == user.id)
        )
        if identity is not None and identity.onboarding_step == onboarding_service.STEP_AWAITING_WEIGHT:
            identity.onboarding_step = onboarding_service.STEP_AWAITING_GOAL
            prompt = onboarding_service.onboarding_prompt_for_step(identity.onboarding_step)
            message += f"\n\n{prompt}" if prompt else ""
        elif identity is not None and identity.onboarding_step == onboarding_service.STEP_COMPLETE:
            message += " Your profile is ready. Send /help to continue."
        return message

    if action.action_type == "update_profile":
        field_key = payload["field"]
        value = payload["value"]
        apply_profile_update(user, field_key, value)
        action.result_payload = {"field": field_key}
        action.status = "completed"
        identity = await db.scalar(
            select(TelegramIdentity).where(TelegramIdentity.user_id == user.id)
        )
        message = f"Saved — {field_key} updated."
        if identity is not None and identity.onboarding_step == onboarding_service.STEP_AWAITING_PROFILE_OPTIN:
            identity.onboarding_step = onboarding_service.STEP_COMPLETE
            message += "\n\nYou're all set. Tell me what you trained, or ask how you're doing."
        return message

    if action.action_type == "create_goal":
        target_date = None
        if payload.get("target_date"):
            target_date = date.fromisoformat(payload["target_date"])
        goal = await create_goal(
            db,
            user.id,
            payload["goal_type"],
            payload["target_value"],
            payload["unit"],
            target_date,
        )
        ref = str(goal.id)[:8]
        action.result_payload = {"goal_ref": ref}
        action.status = "completed"
        identity = await db.scalar(
            select(TelegramIdentity).where(TelegramIdentity.user_id == user.id)
        )
        if identity is not None and identity.onboarding_step == onboarding_service.STEP_AWAITING_GOAL:
            identity.onboarding_step = onboarding_service.STEP_AWAITING_PROFILE_OPTIN
            prompt = onboarding_service.onboarding_prompt_for_step(identity.onboarding_step)
            return f"Goal created (ref {ref}).\n\n{prompt}" if prompt else f"Goal created (ref {ref})."
        return f"Goal created (ref {ref})."

    if action.action_type == "delete_goal":
        goal_id = uuid.UUID(payload["goal_id"])
        removed = await delete_goal(db, user.id, goal_id)
        if not removed:
            action.status = "failed"
            return "Goal not found — it may already be removed."
        action.result_payload = {}
        action.status = "completed"
        return "Goal removed."

    if action.action_type in {"log_workout", "correct_workout"}:
        workout_date = date.fromisoformat(payload["date"])
        sets = payload["sets"]
        if action.action_type == "correct_workout":
            session = await workout_service.correct_workout(db, user.id, uuid.UUID(payload["workout_id"]), payload["expected_revision"], workout_date, sets)
        else:
            session = await workout_service.create_workout(db, user.id, workout_date, sets)
        action.result_payload = {"workout_id": str(session.id)}
        action.status = "completed"
        message = f"Workout saved ({len(sets)} set(s))."

        exercise_names = {s["exercise_name"] for s in sets}
        if len(exercise_names) == 1:
            name = next(iter(exercise_names))
            result = await recommendation_service.get_recommendation(
                db, user.id, name
            )
            if result.decision.value != "insufficient_data":
                label = _DECISION_LABELS.get(
                    result.decision.value, result.decision.value
                )
                message += f"\n\nNext {name}: {label}."
        return message

    action.status = "failed"
    return "Action failed."
