"""Translate private messages into safe domain calls and natural replies."""
import uuid

from sqlalchemy import select

from api.models.db import AgentAction
from api.services import conversation_state_service, onboarding_service
from api.services.audit_service import audit
from api.services.interaction_service import record_interaction
from api.services.user_data import delete_user_data
from api.config import settings
from api.telegram.agent_actions import not_expired, record_agent_action
from api.telegram.callbacks import apply_edit_input, _execute_action
from api.telegram.client import detach_deleted_user, send_telegram_message
from api.telegram.confirmations import is_affirmative, is_negative
from api.telegram.handlers.goals import handle_goals
from api.telegram.handlers.help import handle_help
from api.telegram.handlers.llm import handle_llm_interpretation
from api.telegram.handlers.onboarding import handle_onboarding_goal, handle_onboarding_profile, handle_onboard, handle_skip, handle_start
from api.telegram.handlers.profile import handle_profile
from api.telegram.handlers.summaries import handle_connect_health, handle_dashboard, handle_health, handle_progress, handle_today
from api.telegram.handlers.system import handle_cancel
from api.telegram.handlers.weight import handle_weight
from api.telegram.handlers.workouts import handle_log, handle_recommend
from api.telegram.interpretation import interpret_free_text, is_llm_enabled
from api.telegram.keyboards import confirm_cancel_keyboard, workout_confirm_keyboard
from api.telegram.natural_dispatch import READ_ONLY_INTENTS, classify_with_state, dispatch_natural, handle_pending_natural
from api.telegram.parsing import command, parse_weight
from api.telegram.conversational_fallback import fallback_reply


def _llm_fallback_reason(error: str | None) -> str:
    known = {
        "timeout", "transport_error", "rate_limited", "provider_unavailable",
        "provider_schema_rejected", "provider_model_unavailable", "provider_rejected",
        "schema_invalid", "budget_exhausted", "input_limit", "polish_failed",
    }
    value = (error or "provider_failed").strip().lower().replace(" ", "_")
    return f"llm_{value}" if value in known else "llm_provider_failed"


async def dispatch_message(db, update_id, identity, user, chat_id, text):
    cmd = command(text)
    owner_id = user.id
    savepoint = await db.begin_nested()
    initial_task_id = None
    initial_task_stage = None
    initial_state, initial_payload = await conversation_state_service.get_state(db, owner_id)
    if initial_state is not None and initial_state.kind in {"session_focus", "routine_planning", "routine_logging"}:
        raw_task_id = (initial_payload or {}).get("task_id")
        try:
            initial_task_id = uuid.UUID(str(raw_task_id)) if raw_task_id else None
        except ValueError:
            initial_task_id = None
        initial_task_stage = str((initial_payload or {}).get("stage", ""))[:30] or None

    async def tracked(route, intent, outcome="answered", reason=None, latency=None):
        task_id = None
        task_stage = None
        state, state_payload = await conversation_state_service.get_state(db, owner_id)
        if state is not None and state.kind in {"session_focus", "routine_planning", "routine_logging"}:
            raw_task_id = (state_payload or {}).get("task_id")
            try:
                task_id = uuid.UUID(str(raw_task_id)) if raw_task_id else None
            except ValueError:
                task_id = None
            task_stage = str((state_payload or {}).get("stage", ""))[:30] or None
        if task_id is None:
            task_id, task_stage = initial_task_id, initial_task_stage
        if intent == "routine_review" and task_stage == "awaiting_exercise_clarification":
            outcome = "clarified"
        event_id = await record_interaction(
            db, owner_id, update_id, route, intent, outcome,
            reason_code=reason, latency_ms=latency,
            task_id=task_id, task_stage=task_stage,
        )
        if intent not in {
            "conversation", "unknown", "unsafe", "delete_user", "preferences",
            "ai_preference", "acknowledgement", "task_acknowledgement",
        }:
            from api.services.preferences_service import get_preferences
            prefs = await get_preferences(db, owner_id)
            if prefs.ai_enabled:
                from api.services.conversation_service import remember_exchange
                summary = {
                    "answered": f"FitKit answered the {intent.replace('_', ' ')} request.",
                    "previewed": f"FitKit showed a {intent.replace('_', ' ')} preview and is waiting for confirmation.",
                    "confirmed": f"FitKit confirmed the pending {intent.replace('_', ' ')} action.",
                    "cancelled": f"FitKit cancelled the pending {intent.replace('_', ' ')} action.",
                    "clarified": f"FitKit asked a follow-up about the {intent.replace('_', ' ')} request.",
                }.get(outcome, "FitKit handled the request.")
                await remember_exchange(db, owner_id, text, summary, kind=intent)
        if (
            reason is not None
            or outcome == "completed"
            or intent in {"guidance", "query_guidance"}
        ) and intent not in {"delete_user", "unsafe"}:
            from api.telegram.keyboards import rating_keyboard
            await send_telegram_message(chat_id, "Did that help?", reply_markup=rating_keyboard(event_id))

    async def begin_delete(route="command"):
        await record_agent_action(db, user.id, "delete_user", {})
        await send_telegram_message(chat_id, "This permanently deletes your FitKit profile, workouts, goals, weight history, preferences, and health data. Reply DELETE exactly within 15 minutes to confirm, or say cancel to keep everything.")
        await tracked(route, "delete_user", "previewed")

    try:
        if cmd == "/delete":
            return await begin_delete()
        if cmd == "/cancel":
            await handle_cancel(db, identity, user, chat_id)
            return await tracked("command", "cancel", "cancelled")
        if cmd == "/start":
            await handle_start(identity, user, chat_id)
            return await tracked("command", "start")
        if cmd == "/help":
            await handle_help(chat_id)
            return await tracked("command", "help")
        if cmd in {"/skip", "/onboard"}:
            await (handle_skip if cmd == "/skip" else handle_onboard)(db, identity, user, chat_id)
            return await tracked("command", cmd[1:])
        if cmd == "/preferences":
            from api.telegram.handlers.preferences import handle_preferences
            await handle_preferences(db, user, chat_id, text)
            return await tracked("command", "preferences")
        if cmd == "/target":
            from api.telegram.handlers.targets import handle_target
            await handle_target(db, user, chat_id, text)
            return await tracked("command", "target")
        if cmd == "/correct":
            from api.telegram.handlers.workouts import handle_correct
            await handle_correct(db, user, chat_id, text)
            return await tracked("command", "correct_workout")
        text_handlers = {"/profile": handle_profile, "/goals": handle_goals, "/log": handle_log, "/recommend": handle_recommend}
        if cmd in text_handlers:
            await text_handlers[cmd](db, user, chat_id, text)
            return await tracked("command", cmd[1:], "previewed" if cmd == "/log" else "answered")
        queries = {"/today": handle_today, "/progress": handle_progress, "/health": handle_health, "/connect-health": handle_connect_health, "/dashboard": handle_dashboard}
        if cmd in queries:
            await queries[cmd](db, user, chat_id)
            return await tracked("command", cmd[1:])

        natural = await classify_with_state(db, user.id, text) if settings.conversation_v2 else None
        pending = await db.scalar(select(AgentAction).where(
            AgentAction.user_id == user.id, AgentAction.status == "pending_confirmation", not_expired(),
        ).order_by(AgentAction.created_at.desc()).limit(1).with_for_update())
        if pending is not None:
            if pending.action_type == "delete_user":
                if text == "DELETE":
                    await delete_user_data(db, user.id, current_update_id=update_id)
                    detach_deleted_user()
                    await send_telegram_message(chat_id, "Your FitKit data has been permanently deleted. Send /start to begin again.")
                elif is_negative(text):
                    pending.status = "cancelled"
                    await send_telegram_message(chat_id, "Deletion cancelled. Your data is safe.")
                    await tracked("local", "delete_user", "cancelled")
                else:
                    await send_telegram_message(chat_id, "Deletion is still waiting. Reply exactly DELETE to confirm, or say cancel to keep your data.")
                    await tracked("local", "delete_user", "clarified", "exact_delete_required")
                return
            if is_negative(text):
                pending.status = "cancelled"
                await send_telegram_message(chat_id, "Cancelled — nothing was saved.")
                return await tracked("local", pending.action_type, "cancelled")
            if pending.pending_edit_field:
                await apply_edit_input(db, user, chat_id, pending, text)
                return await tracked("local", pending.action_type, "previewed")
            if is_affirmative(text):
                await send_telegram_message(chat_id, await _execute_action(db, user, pending))
                return await tracked("local", pending.action_type, "confirmed")
            if await handle_pending_natural(db, user, chat_id, pending, text):
                return await tracked("local", pending.action_type, "previewed", "natural_edit")
            if natural is not None and (
                (pending.action_type == "create_goal" and natural.name == "goal_add")
                or (pending.action_type == "update_profile" and natural.name == "profile_update")
                or (pending.action_type == "set_target" and natural.name == "target")
            ):
                await dispatch_natural(db, identity, user, chat_id, natural)
                return await tracked("local", natural.name, "previewed", "preview_replaced")
            if natural is not None and natural.name in READ_ONLY_INTENTS:
                await dispatch_natural(db, identity, user, chat_id, natural)
                keyboard = workout_confirm_keyboard(pending.confirmation_token) if pending.action_type in {"log_workout", "correct_workout"} else confirm_cancel_keyboard(pending.confirmation_token)
                await send_telegram_message(chat_id, "Your earlier preview is still waiting — save, edit, or cancel it when you're ready.", reply_markup=keyboard)
                return await tracked("local", natural.name, "answered", "preview_preserved")
            await send_telegram_message(chat_id, "I’ve still got a preview waiting. Save or cancel it before starting another change; you can also ask a read-only question meanwhile.")
            return await tracked("local", pending.action_type, "clarified", "pending_write")

        if identity.onboarding_step == onboarding_service.STEP_AWAITING_GOAL and text.lower().startswith(("weight ", "frequency ")):
            await handle_onboarding_goal(db, identity, user, chat_id, text)
            return await tracked("onboarding", "create_goal", "previewed")

        if natural is not None:
            if natural.name == "delete":
                return await begin_delete("local")
            if await dispatch_natural(db, identity, user, chat_id, natural):
                return await tracked("local", natural.name, natural.outcome, natural.reason_code)

        if parse_weight(text) is not None:
            await handle_weight(db, identity, user, chat_id, text)
            return await tracked("local", "record_weight", "previewed")

        if is_llm_enabled():
            result = await interpret_free_text(text)
            if result.fallback:
                reply = fallback_reply(text)
                await send_telegram_message(chat_id, reply)
                from api.services.conversation_service import remember_exchange
                await remember_exchange(db, user.id, text, reply, kind="provider_fallback")
                return await tracked(
                    "fallback", "unknown", "clarified",
                    _llm_fallback_reason(result.error), result.latency_ms,
                )
            if result.interpretation and not result.fallback:
                if result.interpretation.confidence < 0.6:
                    reply = "I wasn't quite sure what you meant. Could you add the exercise, goal, or numbers you mean?"
                    await send_telegram_message(chat_id, reply)
                    from api.services.conversation_service import remember_exchange
                    await remember_exchange(db, user.id, text, reply, kind="low_confidence")
                    return await tracked("llm", result.interpretation.intent, "clarified", "low_confidence", result.latency_ms)
                if await handle_llm_interpretation(db, user, chat_id, text, result.interpretation):
                    outcomes = {
                        "unknown": "clarified",
                        "record_weight": "previewed",
                        "log_workout": "previewed",
                        "create_goal": "previewed",
                        "update_profile": "previewed",
                        "session_focus": "started",
                        "routine_review": "completed",
                    }
                    outcome = outcomes.get(result.interpretation.intent, "answered")
                    return await tracked("llm", result.interpretation.intent, outcome, latency=result.latency_ms)

        if identity.onboarding_step == onboarding_service.STEP_AWAITING_GOAL:
            await handle_onboarding_goal(db, identity, user, chat_id, text)
            return await tracked("onboarding", "create_goal", "clarified")
        if identity.onboarding_step == onboarding_service.STEP_AWAITING_PROFILE_OPTIN:
            await handle_onboarding_profile(db, identity, user, chat_id, text)
            return await tracked("onboarding", "update_profile", "clarified")
        await send_telegram_message(chat_id, fallback_reply(text))
        await tracked("fallback", "unknown", "clarified", "unsupported_or_provider_unavailable")
    except (ValueError, KeyError, TypeError):
        await savepoint.rollback()
        audit(db, owner_id, "validation_rejected", {"code": "invalid_details"}, status="rejected")
        await send_telegram_message(chat_id, "Those details don't quite add up. Check the values, units, and date, then try again — nothing was saved.")
        await record_interaction(db, owner_id, update_id, "validation", "unknown", "rejected", reason_code="invalid_details")
