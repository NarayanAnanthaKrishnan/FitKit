"""Execute high-confidence local intents through the existing safe handlers."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from api.models.db import AgentAction
from api.services import conversation_state_service
from api.services.preferences_service import get_preferences
from api.services.units import format_load
from api.telegram.agent_actions import record_agent_action, validate_action
from api.telegram.handlers.goals import handle_goals
from api.telegram.handlers.help import handle_help
from api.telegram.handlers.onboarding import handle_skip
from api.telegram.handlers.profile import handle_profile
from api.telegram.handlers.summaries import (
    handle_connect_health, handle_dashboard, handle_health, handle_progress, handle_today,
)
from api.telegram.handlers.weight import handle_weight
from api.telegram.handlers.workouts import apply_workout_edit, handle_log, handle_recommend
from api.telegram.keyboards import confirm_cancel_keyboard, workout_confirm_keyboard
from api.telegram.client import send_telegram_message
from api.telegram.natural import NaturalIntent, classify_natural
from api.telegram.parsing import parse_weight
from api.telegram.tokens import new_token

READ_ONLY_INTENTS = {
    "greeting", "acknowledgement", "help", "today", "progress", "health",
    "profile", "goals", "recommend", "memory_summary", "session_focus",
    "session_equipment", "guidance",
}


def _task_payload(payload: dict | None = None, **changes) -> dict:
    result = dict(payload or {})
    result.setdefault("task_id", str(uuid.uuid4()))
    result.update(changes)
    return result


def _routine_matches_focus(routine: dict, focus: str) -> bool:
    groups = set(routine.get("muscle_groups") or [])
    expected = {
        "legs": {"quads", "glutes", "calves"},
        "lower body": {"quads", "glutes", "calves"},
        "upper body": {"back", "biceps", "chest", "shoulders", "triceps", "forearms"},
        "push": {"chest", "shoulders", "triceps"},
        "pull": {"back", "biceps", "forearms"},
        "arms": {"biceps", "triceps", "forearms"},
        "core": {"abs"},
    }.get(focus, {part for part in re.split(r"\s+and\s+", focus) if part})
    return bool(groups & expected)


async def classify_with_state(db, user_id, text: str) -> NaturalIntent | None:
    state, payload = await conversation_state_service.get_state(db, user_id)
    if state is not None and state.kind == "feedback_note":
        candidate = classify_natural(text)
        if candidate is not None and candidate.name == "cancel":
            return NaturalIntent("feedback_cancel", outcome="cancelled")
        await conversation_state_service.set_state(db, user_id, "feedback_review", {
            "content": text.strip(), "event_id": payload.get("event_id"),
        })
        return NaturalIntent("feedback_review", outcome="previewed")
    if state is not None and state.kind == "feedback_review":
        return NaturalIntent("feedback_waiting", outcome="clarified", reason_code="feedback_confirmation_required")
    if state is not None and state.kind == "workout_missing_load":
        candidate = classify_natural(text)
        if candidate and candidate.name == "cancel":
            return candidate
        if text.strip().casefold() == "bodyweight":
            await conversation_state_service.clear_state(db, user_id)
            return NaturalIntent("workout", f"{payload['workout']} bodyweight", "previewed")
        if parse_weight(text) is not None:
            await conversation_state_service.clear_state(db, user_id)
            return NaturalIntent("workout", f"{payload['workout']} at {text.strip()}", "previewed")
        if candidate and candidate.name in READ_ONLY_INTENTS:
            return candidate
        return NaturalIntent("state_prompt", outcome="clarified", reason_code="missing_workout_load")
    if state is not None and state.kind in {"session_focus", "routine_planning", "routine_logging"}:
        candidate = classify_natural(text)
        if candidate and candidate.name == "session_mode":
            next_kind = "routine_planning" if candidate.argument == "planning" else "routine_logging"
            await conversation_state_service.set_state(
                db, user_id, next_kind,
                _task_payload(
                    payload,
                    focus=(payload or {}).get("focus", "workout"),
                    stage="awaiting_current_exercises" if candidate.argument == "planning" else "awaiting_log",
                ),
            )
            return NaturalIntent(
                "session_planning" if candidate.argument == "planning" else "session_logging",
                str((payload or {}).get("focus", "workout")),
                "advanced",
            )
        if candidate and candidate.name == "session_equipment":
            await conversation_state_service.set_state(
                db, user_id, "routine_planning",
                _task_payload(
                    payload,
                    equipment=candidate.argument,
                    stage="awaiting_current_exercises",
                ),
            )
            return candidate
        if candidate and candidate.name == "acknowledgement":
            await conversation_state_service.set_state(
                db, user_id, state.kind, _task_payload(payload, stage="paused")
            )
            return NaturalIntent("task_acknowledgement", outcome="paused")
        if candidate and candidate.name == "session_focus":
            await conversation_state_service.set_state(
                db, user_id, "session_focus",
                _task_payload(focus=candidate.argument, stage="awaiting_mode"),
            )
        return candidate
    return classify_natural(text)


async def dispatch_natural(db, identity, user, chat_id: int, intent: NaturalIntent) -> bool:
    name = intent.name
    if name == "greeting":
        await send_telegram_message(chat_id, "Hey! What are we working on today — planning a session, logging one, or checking progress? 💪")
    elif name == "acknowledgement":
        await send_telegram_message(chat_id, "Anytime.")
    elif name == "task_acknowledgement":
        await send_telegram_message(
            chat_id,
            "Anytime — I’ll keep this routine review open briefly. Send your current exercise list when you want me to check it.",
        )
    elif name == "session_focus":
        await conversation_state_service.set_state(
            db, user.id, "session_focus",
            _task_payload(focus=intent.argument, stage="awaiting_mode"),
        )
        await send_telegram_message(
            chat_id,
            f"Nice — {intent.argument} today. Are you planning the session or logging one you finished?",
        )
    elif name == "session_mode":
        await send_telegram_message(
            chat_id, f"What are you {intent.argument} — which workout or muscle group?"
        )
    elif name == "session_planning":
        from api.services.agent_context_service import build_agent_context

        context = await build_agent_context(db, identity, user.id)
        routine = [
            item for item in context["memory"]["recent_routine"]
            if _routine_matches_focus(item, intent.argument)
        ]
        _, state_payload = await conversation_state_service.get_state(db, user.id)
        await conversation_state_service.set_state(
            db, user.id, "routine_planning",
            _task_payload(
                state_payload,
                focus=intent.argument,
                stage="awaiting_current_exercises",
            ),
        )
        if routine:
            exercises = ", ".join(routine[0]["exercises"])
            await send_telegram_message(
                chat_id,
                f"Your latest recorded routine included {exercises}. For this {intent.argument} session, tell me which exercises you want to keep or change, and I’ll check them against your history and targets.",
            )
        else:
            await send_telegram_message(
                chat_id,
                f"I can help improve your {intent.argument} routine, but I don’t have a completed workout to work from yet. Tell me the exercises you already do and what equipment you have; I won’t guess loads or rep targets.",
            )
    elif name == "session_equipment":
        state, payload = await conversation_state_service.get_state(db, user.id)
        focus = str((payload or {}).get("focus", "that workout"))
        if state is None:
            await send_telegram_message(
                chat_id,
                f"Got it — {intent.argument} access. Which current routine or muscle group do you want me to review?",
            )
        else:
            await send_telegram_message(
                chat_id,
                f"Got it — {intent.argument} access for this chat. FitKit improves an existing routine rather than inventing one. Send the exercises you currently use for {focus}, and I’ll check what your recorded history supports.",
            )
    elif name == "session_logging":
        await send_telegram_message(
            chat_id,
            "Tell me the first exercise with sets, reps, and load — for example, ‘squat 3 sets of 8 at 80 kg’. You can add more exercises with semicolons.",
        )
    elif name == "memory_summary":
        from api.services.agent_context_service import describe_memory

        await send_telegram_message(chat_id, await describe_memory(db, identity, user.id))
    elif name == "guidance":
        from api.services.guidance_service import guidance_reply

        await send_telegram_message(
            chat_id, guidance_reply(intent.argument, intent.source_text)
        )
    elif name == "memory_add":
        from api.services.memory_service import proposal_payload

        payload = proposal_payload(intent.argument)
        token = new_token()
        await record_agent_action(
            db, user.id, "remember_preference", payload, confirmation_token=token
        )
        await send_telegram_message(
            chat_id,
            f"Remember this as a long-term preference: “{intent.argument}”? You can review or clear saved memories later.",
            reply_markup=confirm_cancel_keyboard(token),
        )
    elif name == "memory_rejected":
        await send_telegram_message(chat_id, intent.argument + ". Nothing was saved as conversational memory.")
    elif name == "memory_clear":
        token = new_token()
        await record_agent_action(
            db, user.id, "clear_memories", {}, confirmation_token=token
        )
        await send_telegram_message(
            chat_id,
            "Clear all saved conversational preferences? Workouts, goals, profile, and health records will not be changed.",
            reply_markup=confirm_cancel_keyboard(token),
        )
    elif name == "help":
        await handle_help(chat_id)
    elif name == "cancel":
        from api.telegram.handlers.system import handle_cancel
        await handle_cancel(db, identity, user, chat_id)
    elif name == "skip":
        await handle_skip(db, identity, user, chat_id)
    elif name == "today":
        await handle_today(db, user, chat_id)
    elif name == "progress":
        await handle_progress(db, user, chat_id)
    elif name == "health":
        await handle_health(db, user, chat_id)
    elif name == "profile":
        await handle_profile(db, user, chat_id, "/profile")
    elif name == "goals":
        await handle_goals(db, user, chat_id, "/goals")
    elif name == "recommend":
        await handle_recommend(db, user, chat_id, f"/recommend {intent.argument}")
    elif name == "dashboard":
        await handle_dashboard(db, user, chat_id)
    elif name == "connect_health":
        await handle_connect_health(db, user, chat_id)
    elif name == "weight":
        await handle_weight(db, identity, user, chat_id, intent.argument)
    elif name == "workout":
        await handle_log(db, user, chat_id, f"/log {intent.argument}")
    elif name == "workout_missing_load":
        await conversation_state_service.set_state(
            db, user.id, "workout_missing_load", {"workout": intent.argument}
        )
        await send_telegram_message(chat_id, "Got the exercise, sets, and reps. What weight did you use? Include kg or lb — or say bodyweight.")
    elif name == "state_prompt":
        await send_telegram_message(chat_id, "I’m still missing the workout load. Send something like ‘80 kg’, ‘175 lb’, or ‘bodyweight’. You can also say ‘cancel’.")
    elif name == "feedback_review":
        from api.telegram.keyboards import feedback_keyboard
        await send_telegram_message(
            chat_id,
            "Thanks for writing that out. Share this feedback with the FitKit operator? It will be encrypted, kept for 30 days, and may include fitness or health details you typed.",
            reply_markup=feedback_keyboard(),
        )
    elif name == "feedback_waiting":
        from api.telegram.keyboards import feedback_keyboard
        await send_telegram_message(chat_id, "Please choose Share or Not now for the feedback draft.", reply_markup=feedback_keyboard())
    elif name == "feedback_cancel":
        await conversation_state_service.clear_state(db, user.id)
        await send_telegram_message(chat_id, "No problem — the feedback draft was discarded.")
    elif name == "profile_update":
        await handle_profile(db, user, chat_id, f"/profile set {intent.argument}")
    elif name == "goal_add":
        await handle_goals(db, user, chat_id, f"/goals add {intent.argument}")
    elif name == "ai_preference":
        from api.telegram.handlers.preferences import handle_preferences
        await handle_preferences(db, user, chat_id, f"/preferences ai {intent.argument}")
    elif name == "target":
        from api.telegram.handlers.targets import handle_target
        await handle_target(db, user, chat_id, f"/target {intent.argument}")
    elif name == "correct_workout":
        from api.telegram.handlers.workouts import handle_correct
        await handle_correct(db, user, chat_id, f"/correct {intent.argument}")
    else:
        return False
    return True


def _pending_edit(text: str) -> tuple[str, str] | None:
    value = " ".join(text.strip().split())
    patterns = (
        ("weight", r"(?:actually\s+|change(?: the)? weight to\s+|make it\s+)(\d+(?:\.\d+)?\s*(?:kg|kgs|lb|lbs|pounds?)|bodyweight)"),
        ("reps", r"(?:change(?: the)? reps to\s+|reps?\s+(?:to|is)\s+)(\d[\d,\s]*)"),
        ("rpe", r"(?:change(?: the)? rpe to\s+|rpe\s+(?:to|is)\s+)(\d{1,2}|none|n/a)"),
        ("date", r"(?:change(?: the)? date to\s+|date\s+(?:to|is)\s+)(\d{4}-\d{2}-\d{2})"),
    )
    for field, pattern in patterns:
        match = re.fullmatch(pattern, value, re.I)
        if match:
            return field, match.group(1)
    return None


async def handle_pending_natural(db, user, chat_id: int, action: AgentAction, text: str) -> bool:
    edit = _pending_edit(text)
    if edit is not None and action.action_type in {"log_workout", "correct_workout"}:
        raw = "0 kg" if edit[0] == "weight" and edit[1].casefold() == "bodyweight" else edit[1]
        updated, error = apply_workout_edit(action.input_payload, edit[0], raw)
        if error:
            await send_telegram_message(chat_id, error)
            return True
        await validate_action(db, user.id, action.action_type, updated)
        action.input_payload = updated
        action.pending_edit_field = None
        action.confirmation_token = new_token()
        from api.telegram.formatting import workout_preview_from_payload
        await send_telegram_message(chat_id, workout_preview_from_payload(updated), reply_markup=workout_confirm_keyboard(action.confirmation_token))
        return True
    if action.action_type == "record_weight":
        match = re.fullmatch(r"(?:actually\s+|change(?: it| the weight)? to\s+)(.+)", text.strip(), re.I)
        revised = parse_weight(match.group(1)) if match else None
        if revised is not None:
            payload = dict(action.input_payload)
            payload["weight_kg"] = revised
            payload.setdefault("measured_at", datetime.now(timezone.utc).isoformat())
            await validate_action(db, user.id, "record_weight", payload)
            action.input_payload = payload
            action.confirmation_token = new_token()
            units = (await get_preferences(db, user.id)).units
            await send_telegram_message(chat_id, f"Got it — record {format_load(revised, units, digits=2)} instead?", reply_markup=confirm_cancel_keyboard(action.confirmation_token))
            return True
    return False
