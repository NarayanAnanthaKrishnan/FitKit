import os
import re
import secrets
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import (
    AgentAction,
    TelegramIdentity,
    TelegramUpdate,
    UserProfile,
)
from api.services.goal_service import (
    complete_goal,
    create_goal,
    delete_goal,
    get_goal_by_ref,
    list_goals,
)
from api.services.dashboard_service import create_link as create_dashboard_link
from api.services.health_pairing_service import create_pairing
from api.services.profile_service import (
    PROFILE_FIELD_MAP,
    apply_profile_update,
    validate_profile_field,
)
from api.services.summary_service import (
    health_snapshot,
    progress_summary,
    today_snapshot,
)
from api.services.telegram_client import (
    answer_callback_query as _answer_callback_query,
    build_inline_keyboard,
    send_message as _send_message,
)
from api.services.user_data import delete_user_data
from api.services.weight_service import record_weight
from api.services import recommendation_service, workout_service
from api.services.workout_parser import parse_workouts

router = APIRouter(prefix="/integrations/telegram", tags=["telegram"])

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
_WEIGHT_PATTERN = re.compile(
    r"^\s*(?:i\s+weigh|weight\s*(?:is|:)?)?\s*"
    r"(\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)?\s*(?:today)?\s*$",
    re.IGNORECASE,
)
_PROFILE_SET_RE = re.compile(r"^/profile\s+set\s+(\S+)\s+(.+)$", re.IGNORECASE)
_WEIGHT_GOAL_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(kg|lbs?)\s*(?:by\s+(\d{4}-\d{2}-\d{2}))?\s*$",
    re.IGNORECASE,
)
_FREQUENCY_GOAL_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(?:x\s*)?(?:per\s*week|/week|sessions?\s*(?:per\s*week|/week))$",
    re.IGNORECASE,
)

_CONFIRM_PREFIX = "confirm:"
_CANCEL_PREFIX = "cancel:"
_EDIT_PREFIX = "edit:"
_EDIT_FIELD_PREFIX = "edit_field:"

_EDIT_FIELDS = [
    ("Weight", "weight"),
    ("Reps", "reps"),
    ("RPE", "rpe"),
    ("Date", "date"),
]
_EDIT_PROMPTS = {
    "weight": "Send the new weight, e.g. '82.5 kg' or '180 lb'.",
    "reps": "Send the new reps, e.g. '8' or '8, 8, 7'.",
    "rpe": "Send RPE 1–10, or 'none' to remove it.",
    "date": "Send the new date as YYYY-MM-DD.",
}
_EDIT_WEIGHT_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)?\s*$",
    re.IGNORECASE,
)
_EDIT_REPS_RE = re.compile(r"^\s*(\d[\d,\s]*)$")

_DECISION_LABELS = {
    "increase_load": "Increase load",
    "hold": "Hold",
    "deload": "Deload",
    "insufficient_data": "Not enough data yet",
}


async def send_telegram_message(
    chat_id: int, text: str, reply_markup: dict | None = None
) -> None:
    """Send one text response through Telegram's Bot API."""
    await _send_message(chat_id, text, reply_markup)


async def answer_callback_query(callback_query_id: str, text: str | None = None) -> None:
    """Acknowledge a Telegram callback query."""
    await _answer_callback_query(callback_query_id, text)


def _telegram_secret_matches(received: str | None) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    return bool(expected and received and received == expected)


def _extract_message(update: dict[str, Any]) -> tuple[int, int, str, dict[str, Any]] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender = message.get("from")
    chat = message.get("chat")
    text = message.get("text")
    if not isinstance(sender, dict) or not isinstance(chat, dict) or not isinstance(text, str):
        return None
    # Fitness and deletion messages may contain sensitive personal data.
    if chat.get("type") != "private":
        return None
    telegram_user_id = sender.get("id")
    chat_id = chat.get("id")
    if not isinstance(telegram_user_id, int) or not isinstance(chat_id, int):
        return None
    return telegram_user_id, chat_id, text.strip(), sender


def _extract_callback(
    update: dict[str, Any],
) -> tuple[int, int, str, dict[str, Any], str] | None:
    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return None
    sender = callback.get("from")
    message = callback.get("message")
    data = callback.get("data")
    callback_id = callback.get("id")
    if not isinstance(sender, dict) or not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    telegram_user_id = sender.get("id")
    chat_id = chat.get("id")
    if not isinstance(telegram_user_id, int) or not isinstance(chat_id, int):
        return None
    if not isinstance(data, str) or not isinstance(callback_id, str):
        return None
    return telegram_user_id, chat_id, data, sender, callback_id


def _parse_weight(text: str) -> float | None:
    match = _WEIGHT_PATTERN.match(text)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "kg").lower()
    if unit in {"lb", "lbs", "pound", "pounds"}:
        value *= 0.45359237
    if not 20 <= value <= 500:
        return None
    return round(value, 2)


def _command(text: str) -> str:
    return text.split(maxsplit=1)[0].lower().split("@", 1)[0]


def _new_token() -> str:
    return secrets.token_hex(8)


def _confirm_cancel_keyboard(token: str, confirm_label: str = "Save") -> dict:
    return build_inline_keyboard(
        [[(confirm_label, f"{_CONFIRM_PREFIX}{token}"), ("Cancel", f"{_CANCEL_PREFIX}{token}")]]
    )


def _workout_confirm_keyboard(token: str) -> dict:
    return build_inline_keyboard(
        [[
            ("Save", f"{_CONFIRM_PREFIX}{token}"),
            ("Edit", f"{_EDIT_PREFIX}{token}"),
            ("Cancel", f"{_CANCEL_PREFIX}{token}"),
        ]]
    )


def _field_selection_keyboard(token: str) -> dict:
    rows = [
        [
            (label, f"{_EDIT_FIELD_PREFIX}{token}:{field}")
            for label, field in _EDIT_FIELDS[:2]
        ],
        [
            (label, f"{_EDIT_FIELD_PREFIX}{token}:{field}")
            for label, field in _EDIT_FIELDS[2:]
        ],
        [("Cancel", f"{_CANCEL_PREFIX}{token}")],
    ]
    return build_inline_keyboard(rows)


async def _get_or_create_identity(
    db: AsyncSession,
    telegram_user_id: int,
    chat_id: int,
    sender: dict[str, Any],
) -> TelegramIdentity:
    identity = await db.scalar(
        select(TelegramIdentity).where(
            TelegramIdentity.telegram_user_id == telegram_user_id
        )
    )
    now = datetime.now(timezone.utc)
    if identity is not None:
        identity.telegram_chat_id = chat_id
        identity.username = sender.get("username")
        identity.first_name = sender.get("first_name")
        identity.last_name = sender.get("last_name")
        identity.last_seen_at = now
        return identity

    # Create the profile and identity together. The identity insert is an
    # atomic conflict-safe operation so concurrent Telegram updates cannot
    # create two accounts for one Telegram user.
    user = UserProfile()
    db.add(user)
    await db.flush()
    result = await db.execute(
        pg_insert(TelegramIdentity)
        .values(
            user_id=user.id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=chat_id,
            username=sender.get("username"),
            first_name=sender.get("first_name"),
            last_name=sender.get("last_name"),
            onboarding_step="awaiting_weight",
            created_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_nothing(index_elements=["telegram_user_id"])
        .returning(TelegramIdentity.id)
    )
    identity_id = result.scalar_one_or_none()
    if identity_id is None:
        await db.delete(user)
        await db.flush()
        identity = await db.scalar(
            select(TelegramIdentity).where(
                TelegramIdentity.telegram_user_id == telegram_user_id
            )
        )
        if identity is None:
            raise RuntimeError("Telegram identity could not be resolved")
        identity.telegram_chat_id = chat_id
        identity.username = sender.get("username")
        identity.first_name = sender.get("first_name")
        identity.last_name = sender.get("last_name")
        identity.last_seen_at = now
        return identity
    identity = await db.get(TelegramIdentity, identity_id)
    if identity is None:
        raise RuntimeError("Telegram identity could not be created")
    return identity


async def _record_update_once(
    db: AsyncSession, update_id: int, telegram_user_id: int | None
) -> bool:
    result = await db.execute(
        pg_insert(TelegramUpdate)
        .values(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            received_at=datetime.now(timezone.utc),
            status="received",
        )
        .on_conflict_do_nothing(index_elements=["update_id"])
    )
    return result.rowcount == 1


async def _mark_update(
    db: AsyncSession, update_id: int, status: str = "processed"
) -> None:
    await db.execute(
        TelegramUpdate.__table__.update()
        .where(TelegramUpdate.update_id == update_id)
        .values(processed_at=datetime.now(timezone.utc), status=status)
    )


async def _record_agent_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    action_type: str,
    input_payload: dict,
    status: str = "pending_confirmation",
    confirmation_token: str | None = None,
) -> AgentAction:
    action = AgentAction(
        user_id=user_id,
        action_type=action_type,
        input_payload=input_payload,
        status=status,
        confirmation_token=confirmation_token,
    )
    db.add(action)
    await db.flush()
    return action


async def _pending_action(
    db: AsyncSession, user_id: uuid.UUID, token: str
) -> AgentAction | None:
    return await db.scalar(
        select(AgentAction).where(
            AgentAction.user_id == user_id,
            AgentAction.confirmation_token == token,
            AgentAction.status == "pending_confirmation",
        )
    )


async def _pending_edit_action(
    db: AsyncSession, user_id: uuid.UUID
) -> AgentAction | None:
    """The most-recent pending action that is awaiting an edit value."""
    return await db.scalar(
        select(AgentAction)
        .where(
            AgentAction.user_id == user_id,
            AgentAction.status == "pending_confirmation",
            AgentAction.pending_edit_field.is_not(None),
        )
        .order_by(AgentAction.created_at.desc())
        .limit(1)
    )


@router.post("/webhook")
async def telegram_webhook(
    update: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    secret: str | None = Header(default=None, alias=TELEGRAM_SECRET_HEADER),
):
    if not _telegram_secret_matches(secret):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        raise HTTPException(status_code=400, detail="Telegram update_id is required")

    extracted = _extract_message(update)
    callback = _extract_callback(update)
    telegram_user_id = extracted[0] if extracted else (callback[0] if callback else None)
    if not await _record_update_once(db, update_id, telegram_user_id):
        return {"ok": True, "duplicate": True}

    if callback is not None:
        await _handle_callback(db, callback)
        await _mark_update(db, update_id)
        return {"ok": True}

    if extracted is None:
        await _mark_update(db, update_id, status="ignored")
        return {"ok": True, "ignored": True}

    telegram_user_id, chat_id, text, sender = extracted
    if not text:
        await _mark_update(db, update_id, status="ignored")
        return {"ok": True, "ignored": True}

    identity = await _get_or_create_identity(db, telegram_user_id, chat_id, sender)
    user = await db.get(UserProfile, identity.user_id)
    if user is None:
        raise HTTPException(status_code=500, detail="Telegram user profile not found")

    await _dispatch_message(db, update_id, identity, user, chat_id, text)
    await _mark_update(db, update_id)
    return {"ok": True}


async def _dispatch_message(
    db: AsyncSession,
    update_id: int,
    identity: TelegramIdentity,
    user: UserProfile,
    chat_id: int,
    text: str,
) -> None:
    command = _command(text)

    # A pending inline edit captures the next free-text reply (but never a
    # slash command, so /cancel still works).
    if not text.startswith("/"):
        pending_edit = await _pending_edit_action(db, user.id)
        if pending_edit is not None:
            await _apply_edit_input(db, user, chat_id, pending_edit, text)
            return

    if command == "/start":
        await _handle_start(identity, user, chat_id)
        return
    if command == "/help":
        await _handle_help(chat_id)
        return
    if command == "/delete":
        identity.onboarding_step = "awaiting_delete_confirmation"
        await send_telegram_message(
            chat_id,
            "This will permanently delete your FitKit profile, weight history, "
            "workouts, goals, and health data. This cannot be undone.\n\n"
            "Reply DELETE to confirm, or /cancel to keep your data.",
        )
        return
    if command == "/cancel":
        await _handle_cancel(db, identity, user, chat_id)
        return
    if command == "/profile":
        await _handle_profile(db, user, chat_id, text)
        return
    if command == "/goals":
        await _handle_goals(db, user, chat_id, text)
        return
    if command == "/today":
        await _handle_today(db, user, chat_id)
        return
    if command == "/progress":
        await _handle_progress(db, user, chat_id)
        return
    if command == "/health":
        await _handle_health(db, user, chat_id)
        return
    if command == "/connect-health":
        await _handle_connect_health(db, user, chat_id)
        return
    if command == "/dashboard":
        await _handle_dashboard(db, user, chat_id)
        return
    if command == "/log":
        await _handle_log(db, user, chat_id, text)
        return
    if command == "/recommend":
        await _handle_recommend(db, user, chat_id, text)
        return

    if identity.onboarding_step == "awaiting_delete_confirmation":
        if text.upper() != "DELETE":
            await send_telegram_message(
                chat_id,
                "Deletion is still pending. Reply DELETE to confirm, or /cancel to keep your data.",
            )
            return
        await delete_user_data(db, user.id, current_update_id=update_id)
        await send_telegram_message(
            chat_id,
            "Your FitKit data has been permanently deleted. "
            "Send /start if you want to begin again.",
        )
        return

    if identity.onboarding_step == "awaiting_weight" or _parse_weight(text) is not None:
        await _handle_weight(db, identity, user, chat_id, text)
        return

    await send_telegram_message(
        chat_id,
        "I received your message. Send /help to see the available commands.",
    )


async def _handle_start(identity: TelegramIdentity, user: UserProfile, chat_id: int) -> None:
    if user.weight_kg is not None:
        identity.onboarding_step = "complete"
        reply = (
            f"Welcome back{', ' + (identity.first_name or '') if identity.first_name else ''}! "
            "Your profile is ready. Send /help to see what I can do."
        )
    else:
        identity.onboarding_step = "awaiting_weight"
        reply = (
            "Welcome to FitKit! I can help you track workouts, weight, "
            "activity, and progress. What is your current weight? "
            "Reply with a value such as 80 kg."
        )
    await send_telegram_message(chat_id, reply)


async def _handle_help(chat_id: int) -> None:
    await send_telegram_message(
        chat_id,
        "/start - start or resume setup\n"
        "/help - show this help\n"
        "/profile - view or update your profile\n"
        "/goals - view or manage goals\n"
        "/today - today's snapshot\n"
        "/progress - weight and goal progress\n"
        "/health - recovery and health metrics\n"
        "/connect-health - pair Health Auto Export with your account\n"
        "/dashboard - get a private, temporary dashboard link\n"
        "/log - log a workout (e.g. /log bench press 3x8 at 80 kg, rpe 8)\n"
        "        multiple exercises: /log squat 3x5 @ 100kg; bench 3x8 @ 80kg\n"
        "/recommend - get a recommendation (e.g. /recommend bench press)\n"
        "/delete - permanently delete your FitKit data\n"
        "/cancel - cancel the current confirmation\n"
        "You can send a weight such as '75 kg' to record it.",
    )


async def _handle_cancel(
    db: AsyncSession, identity: TelegramIdentity, user: UserProfile, chat_id: int
) -> None:
    if identity.onboarding_step == "awaiting_delete_confirmation":
        identity.onboarding_step = (
            "complete" if user.weight_kg is not None else "awaiting_weight"
        )
        await send_telegram_message(chat_id, "Deletion cancelled. Your data is safe.")
        return

    action = await db.scalar(
        select(AgentAction)
        .where(
            AgentAction.user_id == user.id,
            AgentAction.status == "pending_confirmation",
        )
        .order_by(AgentAction.created_at.desc())
        .limit(1)
    )
    if action is not None:
        action.status = "cancelled"
        await send_telegram_message(chat_id, "Cancelled.")
    else:
        await send_telegram_message(chat_id, "Nothing to cancel.")


async def _handle_weight(
    db: AsyncSession, identity: TelegramIdentity, user: UserProfile, chat_id: int, text: str
) -> None:
    weight_kg = _parse_weight(text)
    if weight_kg is None:
        await send_telegram_message(
            chat_id,
            "Please send your current weight, for example: 80 kg or 176 lb.",
        )
        return

    await record_weight(
        db, user.id, weight_kg, datetime.now(timezone.utc), source="telegram"
    )
    await _record_agent_action(
        db,
        user.id,
        "record_weight",
        {"weight_kg": weight_kg, "unit": "kg"},
        status="completed",
    )

    was_onboarding = identity.onboarding_step == "awaiting_weight"
    if was_onboarding:
        identity.onboarding_step = "complete"
        message = (
            f"Saved — your current weight is {weight_kg:.2f} kg. "
            "Your profile is ready. Send /help to continue."
        )
    else:
        message = f"Saved — your current weight is {weight_kg:.2f} kg."
    await send_telegram_message(chat_id, message)


async def _handle_profile(
    db: AsyncSession, user: UserProfile, chat_id: int, text: str
) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) == 1 or not parts[1].strip():
        await send_telegram_message(chat_id, _profile_display(user))
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

    token = _new_token()
    await _record_agent_action(
        db,
        user.id,
        "update_profile",
        {"field": field_key, "value": value},
        confirmation_token=token,
    )
    await send_telegram_message(
        chat_id,
        f"Update {field_key} to {value}?",
        reply_markup=_confirm_cancel_keyboard(token),
    )


def _profile_display(user: UserProfile) -> str:
    def fmt(value: object) -> str:
        return str(value) if value is not None else "not set"

    lines = [
        f"Weight: {user.weight_kg:.1f} kg"
        if user.weight_kg is not None
        else "Weight: not set",
        f"Age: {fmt(user.age)}",
        f"Sex: {fmt(user.sex)}",
        f"Resting HR: {fmt(user.resting_hr)}",
        f"Max HR: {fmt(user.max_hr)}",
        f"Calibration: {user.personal_calibration_factor}",
    ]
    return (
        "Your profile\n"
        + "\n".join(lines)
        + "\n\nTo update: /profile set <field> <value>"
    )


async def _handle_goals(
    db: AsyncSession, user: UserProfile, chat_id: int, text: str
) -> None:
    parts = text.split(maxsplit=1)
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not rest:
        await _send_goal_list(db, user, chat_id)
        return

    sub, _, arg = rest.partition(" ")
    arg = arg.strip()
    if sub == "add":
        await _goal_add(db, user, chat_id, arg)
    elif sub == "complete":
        await _goal_complete(db, user, chat_id, arg)
    elif sub == "remove":
        await _goal_remove(db, user, chat_id, arg)
    else:
        await send_telegram_message(
            chat_id,
            "Usage: /goals [add <goal> | complete <ref> | remove <ref>]",
        )


async def _send_goal_list(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    goals = await list_goals(db, user.id)
    if not goals:
        await send_telegram_message(
            chat_id,
            "You have no goals yet.\n"
            "Examples:\n"
            "  /goals add weight 75 kg by 2026-12-31\n"
            "  /goals add frequency 3 per week",
        )
        return

    lines = ["Your goals:"]
    for goal in goals:
        ref = str(goal.id)[:8]
        if goal.goal_type == "weight":
            target = f"{goal.target_value} {goal.unit}"
            if goal.target_date:
                target += f" by {goal.target_date}"
            lines.append(f"  {ref} · weight {target} ({goal.status})")
        else:
            lines.append(
                f"  {ref} · {goal.target_value:.0f} sessions/week ({goal.status})"
            )
    await send_telegram_message(chat_id, "\n".join(lines))


async def _goal_add(db: AsyncSession, user: UserProfile, chat_id: int, arg: str) -> None:
    spec, error = _parse_goal_spec(arg)
    if error:
        await send_telegram_message(chat_id, error)
        return

    payload = {
        "goal_type": spec["goal_type"],
        "target_value": spec["target_value"],
        "unit": spec["unit"],
        "target_date": spec["target_date"].isoformat() if spec["target_date"] else None,
    }
    token = _new_token()
    await _record_agent_action(
        db, user.id, "create_goal", payload, confirmation_token=token
    )
    await send_telegram_message(
        chat_id,
        _goal_preview(spec),
        reply_markup=_confirm_cancel_keyboard(token),
    )


async def _goal_complete(
    db: AsyncSession, user: UserProfile, chat_id: int, ref: str
) -> None:
    goal = await get_goal_by_ref(db, user.id, ref)
    if goal is None:
        await send_telegram_message(
            chat_id, f"No goal matches '{ref}'. Use /goals to list them."
        )
        return
    await complete_goal(db, user.id, goal.id)
    await send_telegram_message(chat_id, f"Goal {ref} marked complete.")


async def _goal_remove(
    db: AsyncSession, user: UserProfile, chat_id: int, ref: str
) -> None:
    goal = await get_goal_by_ref(db, user.id, ref)
    if goal is None:
        await send_telegram_message(
            chat_id, f"No goal matches '{ref}'. Use /goals to list them."
        )
        return
    token = _new_token()
    await _record_agent_action(
        db,
        user.id,
        "delete_goal",
        {"goal_id": str(goal.id), "ref": ref},
        confirmation_token=token,
    )
    await send_telegram_message(
        chat_id,
        f"Remove goal {ref}?",
        reply_markup=_confirm_cancel_keyboard(token, "Remove"),
    )


def _parse_goal_spec(arg: str) -> tuple[dict, str | None]:
    kind, _, rest = arg.partition(" ")
    kind = kind.lower()
    rest = rest.strip()

    if kind == "weight":
        match = _WEIGHT_GOAL_RE.match(rest)
        if not match:
            return {}, "Usage: /goals add weight <value> kg|lb [by YYYY-MM-DD]"
        value = float(match.group(1))
        unit = "lb" if match.group(2).lower() in {"lb", "lbs"} else "kg"
        target_date = None
        if match.group(3):
            try:
                target_date = date.fromisoformat(match.group(3))
            except ValueError:
                return {}, "Target date must be YYYY-MM-DD."
        return (
            {
                "goal_type": "weight",
                "target_value": value,
                "unit": unit,
                "target_date": target_date,
            },
            None,
        )

    if kind == "frequency":
        match = _FREQUENCY_GOAL_RE.match(rest)
        if not match:
            return {}, "Usage: /goals add frequency <sessions> per week"
        value = float(match.group(1))
        if value <= 0:
            return {}, "Frequency must be greater than zero."
        return (
            {
                "goal_type": "frequency",
                "target_value": value,
                "unit": "per_week",
                "target_date": None,
            },
            None,
        )

    return {}, "Goal type must be 'weight' or 'frequency'."


def _goal_preview(spec: dict) -> str:
    if spec["goal_type"] == "weight":
        suffix = f" by {spec['target_date']}" if spec["target_date"] else ""
        return f"New goal: weight {spec['target_value']} {spec['unit']}{suffix}. Save it?"
    return f"New goal: {spec['target_value']:.0f} sessions per week. Save it?"


async def _handle_today(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    snapshot = await today_snapshot(db, user.id)
    await send_telegram_message(chat_id, _format_today(snapshot))


async def _handle_progress(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    summary = await progress_summary(db, user.id)
    await send_telegram_message(chat_id, _format_progress(summary))


async def _handle_health(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    health = await health_snapshot(db, user.id)
    await send_telegram_message(chat_id, _format_health(health))


async def _handle_connect_health(
    db: AsyncSession, user: UserProfile, chat_id: int
) -> None:
    token, _ = await create_pairing(db, user.id)
    base_url = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    endpoint = (
        f"{base_url}/ingest/health"
        if base_url
        else "https://<your-deployed-host>/ingest/health"
    )
    await send_telegram_message(
        chat_id,
        "Connect Health Auto Export to your FitKit account:\n\n"
        "1. Install Health Auto Export on your iPhone and grant it Health access.\n"
        "2. Add a custom REST export with this endpoint:\n"
        f"{endpoint}\n"
        "3. Add this header:\n"
        f"X-Health-Pairing-Token: {token}\n\n"
        "Keep this token private — anyone with it can write to your health data. "
        "Send /connect-health again to rotate it.",
    )


async def _handle_dashboard(
    db: AsyncSession, user: UserProfile, chat_id: int
) -> None:
    token, _ = await create_dashboard_link(db, user.id)
    base_url = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    if not base_url:
        await send_telegram_message(
            chat_id,
            "Dashboard links need a PUBLIC_BASE_URL to be configured. "
            "Ask the operator to set it, then try /dashboard again.",
        )
        return
    url = f"{base_url}/dashboard?token={token}"
    await send_telegram_message(
        chat_id,
        f"Your private dashboard is ready (expires soon):\n{url}\n\n"
        "Do not share this link.",
    )


def _format_today(snapshot: dict) -> str:
    weight = snapshot.get("weight_kg")
    lines = [f"Weight: {weight:.1f} kg" if weight is not None else "Weight: not recorded"]

    health = snapshot.get("health") or {}
    if health.get("has_data"):
        parts = []
        if health["latest_hrv"] is not None:
            parts.append(f"HRV {health['latest_hrv']} ms")
        if health["latest_sleep_hours"] is not None:
            parts.append(f"sleep {health['latest_sleep_hours']} h")
        if health["latest_resting_hr"] is not None:
            parts.append(f"resting HR {health['latest_resting_hr']}")
        lines.append("Recovery: " + (", ".join(parts) if parts else "no recent readings"))
    else:
        lines.append("Recovery: no health data connected yet")

    workout = snapshot.get("last_workout")
    if workout is not None:
        exercises = ", ".join(workout["exercises"]) or "no exercises"
        lines.append(f"Last workout: {workout['date']} ({exercises})")
    else:
        lines.append("Last workout: none logged yet")

    return "Today\n" + "\n".join(lines)


def _format_progress(summary: dict) -> str:
    lines = []
    weight = summary["weight"]
    if weight["latest_kg"] is None:
        lines.append("Weight: no measurements yet")
    else:
        line = f"Weight: {weight['latest_kg']:.1f} kg"
        if weight["change_7d"] is not None:
            line += f" (7d: {weight['change_7d']:+.1f} kg)"
        if weight["change_30d"] is not None:
            line += f" (30d: {weight['change_30d']:+.1f} kg)"
        lines.append(line)

    goals = summary["goals"]
    if not goals:
        lines.append("Goals: none active — set one with /goals add")
    else:
        lines.append("Goals:")
        for goal in goals:
            if goal["type"] == "frequency":
                lines.append(
                    f"  {goal['ref']} · {goal['current']}/{goal['target']:.0f} "
                    f"{goal['unit']} ({goal['progress_pct']}%)"
                )
            else:
                current = f"{goal['current']:.1f}" if goal["current"] is not None else "?"
                lines.append(
                    f"  {goal['ref']} · {current} {goal['unit']} "
                    f"/ target {goal['target']} {goal['unit']}"
                )

    return "Progress\n" + "\n".join(lines)


def _format_health(health: dict) -> str:
    if not health.get("has_data"):
        return (
            "No health data is connected yet. Connect Health Auto Export or log "
            "health metrics to see HRV, sleep, and resting HR here."
        )

    lines = []
    if health["latest_hrv"] is not None:
        lines.append(f"Latest HRV: {health['latest_hrv']} ms")
    if health["latest_sleep_hours"] is not None:
        lines.append(f"Latest sleep: {health['latest_sleep_hours']} h")
    if health["latest_resting_hr"] is not None:
        lines.append(f"Latest resting HR: {health['latest_resting_hr']} bpm")
    if health["hrv_baseline_7day"] is not None:
        lines.append(f"HRV baseline (7d): {health['hrv_baseline_7day']} ms")
    return "Health\n" + "\n".join(lines)


async def _handle_log(
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

    parsed_workouts, error = parse_workouts(arg)
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
                chat_id, _exercise_clarification(parsed.exercise_query, candidates)
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

    payload = {"date": date.today().isoformat(), "sets": sets, "exercises": exercises}
    token = _new_token()
    await _record_agent_action(
        db, user.id, "log_workout", payload, confirmation_token=token
    )
    await send_telegram_message(
        chat_id,
        _workout_preview_from_payload(payload),
        reply_markup=_workout_confirm_keyboard(token),
    )


async def _handle_recommend(
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
            chat_id, _exercise_clarification(arg, candidates)
        )
        return

    exercise = await workout_service.get_exercise(db, canonical)
    display_name = exercise.display_name if exercise else canonical
    result = await recommendation_service.get_recommendation(db, user.id, canonical)
    await send_telegram_message(
        chat_id, _format_recommendation(display_name, result)
    )


def _exercise_clarification(query: str, candidates: list[str]) -> str:
    if candidates:
        return (
            f"I couldn't match '{query}' uniquely. Did you mean one of these?\n"
            + "\n".join(f"  • {c}" for c in candidates)
            + "\nPlease resend with the exact name."
        )
    return (
        f"I couldn't find exercise '{query}'. "
        "Please use a name from the exercise list."
    )


def _workout_preview_from_payload(payload: dict) -> str:
    exercises = payload.get("exercises", [])
    sets = payload.get("sets", [])
    by_exercise: dict[str, list[dict]] = {}
    for s in sets:
        by_exercise.setdefault(s["exercise_name"], []).append(s)

    lines = []
    for ex in exercises:
        ex_sets = by_exercise.get(ex["name"], [])
        if ex_sets:
            lines.append(_exercise_line(ex["display"], ex_sets))
    return "I understood:\n" + "\n".join(lines) + "\nSave this workout?"


def _exercise_line(display_name: str, ex_sets: list[dict]) -> str:
    weight = ex_sets[0]["weight_kg"]
    reps = [s["reps"] for s in ex_sets]
    if len(set(reps)) == 1:
        reps_part = f"{len(ex_sets)} sets × {reps[0]} reps"
    else:
        reps_part = "reps " + ", ".join(str(r) for r in reps)

    rpe_values = sorted({s["rpe"] for s in ex_sets if s["rpe"] is not None})
    parts = [display_name, reps_part, f"{weight} kg"]
    if rpe_values:
        parts.append("RPE " + ", ".join(str(r) for r in rpe_values))
    return " — ".join(parts)


def _format_recommendation(display_name: str, result) -> str:
    lines = [f"Recommendation — {display_name}:"]
    label = _DECISION_LABELS.get(result.decision.value, result.decision.value)
    lines.append(f"Decision: {label}")
    if result.acwr_ratio is not None:
        lines.append(f"ACWR: {result.acwr_ratio} ({result.acwr_flag})")
    else:
        lines.append(f"ACWR: {result.acwr_flag}")
    if result.recovery_override is not None:
        lines.append(f"Recovery override: {result.recovery_override}")
    return "\n".join(lines)


async def _handle_callback(
    db: AsyncSession, callback: tuple[int, int, str, dict[str, Any], str]
) -> None:
    telegram_user_id, chat_id, data, sender, callback_id = callback
    identity = await _get_or_create_identity(db, telegram_user_id, chat_id, sender)
    user = await db.get(UserProfile, identity.user_id)
    if user is None:
        await answer_callback_query(callback_id, "Session not found. Send /start.")
        return

    if data.startswith(_CONFIRM_PREFIX):
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
    action = await _pending_action(db, user.id, token)
    if action is None:
        await answer_callback_query(callback_id, "This action is no longer available.")
        return
    message = await _execute_action(db, user, action)
    await answer_callback_query(callback_id)
    await send_telegram_message(chat_id, message)


async def _cancel_action(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    callback_id: str,
    token: str,
) -> None:
    action = await _pending_action(db, user.id, token)
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
    action = await _pending_action(db, user.id, token)
    if action is None:
        await answer_callback_query(callback_id, "This action is no longer available.")
        return
    if action.action_type != "log_workout":
        await answer_callback_query(callback_id, "This action can't be edited.")
        return
    await answer_callback_query(callback_id)
    await send_telegram_message(
        chat_id,
        "What would you like to change?",
        reply_markup=_field_selection_keyboard(token),
    )


async def _edit_field_action(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    callback_id: str,
    spec: str,
) -> None:
    token, _, field = spec.rpartition(":")
    action = await _pending_action(db, user.id, token)
    if action is None:
        await answer_callback_query(callback_id, "This action is no longer available.")
        return
    if action.action_type != "log_workout" or field not in _EDIT_PROMPTS:
        await answer_callback_query(callback_id, "Unknown field.")
        return
    action.pending_edit_field = field
    await answer_callback_query(callback_id)
    await send_telegram_message(chat_id, _EDIT_PROMPTS[field])


async def _apply_edit_input(
    db: AsyncSession,
    user: UserProfile,
    chat_id: int,
    action: AgentAction,
    text: str,
) -> None:
    updated, error = _apply_workout_edit(action.input_payload, action.pending_edit_field, text)
    if error:
        await send_telegram_message(chat_id, error)
        return
    action.input_payload = updated
    action.pending_edit_field = None
    await send_telegram_message(
        chat_id,
        _workout_preview_from_payload(updated),
        reply_markup=_workout_confirm_keyboard(action.confirmation_token),
    )


def _apply_workout_edit(
    payload: dict, field: str | None, raw: str
) -> tuple[dict, str | None]:
    """Return an updated workout payload for a single edited field.

    Never mutates ``payload`` in place; the caller assigns the returned copy so
    SQLAlchemy detects the change to the JSONB column.
    """
    updated = dict(payload)
    updated["sets"] = [dict(s) for s in payload.get("sets", [])]
    text = (raw or "").strip()

    if field == "weight":
        match = _EDIT_WEIGHT_RE.match(text)
        if not match:
            return updated, "Send the new weight, e.g. '82.5 kg' or '180 lb'."
        value = float(match.group(1))
        unit = (match.group(2) or "kg").lower()
        if unit in {"lb", "lbs", "pound", "pounds"}:
            value = round(value * 0.45359237, 2)
        if not 0 < value <= 1000:
            return updated, "Weight must be between 0 and 1000 kg."
        for s in updated["sets"]:
            s["weight_kg"] = value
        return updated, None

    if field == "reps":
        if not _EDIT_REPS_RE.match(text):
            return updated, "Send the new reps, e.g. '8' or '8, 8, 7'."
        values = [int(p) for p in re.split(r"[,\s]+", text) if p]
        if any(not 1 <= v <= 100 for v in values):
            return updated, "Reps must be between 1 and 100."
        if len(values) == 1:
            for s in updated["sets"]:
                s["reps"] = values[0]
        elif len(values) == len(updated["sets"]):
            for s, v in zip(updated["sets"], values):
                s["reps"] = v
        else:
            return updated, (
                f"This workout has {len(updated['sets'])} sets; send one rep count "
                f"or {len(updated['sets'])} comma-separated counts."
            )
        return updated, None

    if field == "rpe":
        if text.lower() in {"none", "-", "n/a", "na"}:
            for s in updated["sets"]:
                s["rpe"] = None
            return updated, None
        try:
            value = int(text)
        except ValueError:
            return updated, "RPE must be a number 1–10, or 'none' to remove it."
        if not 1 <= value <= 10:
            return updated, "RPE must be between 1 and 10."
        for s in updated["sets"]:
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


async def _execute_action(
    db: AsyncSession, user: UserProfile, action: AgentAction
) -> str:
    payload = action.input_payload

    if action.action_type == "update_profile":
        field_key = payload["field"]
        value = payload["value"]
        apply_profile_update(user, field_key, value)
        action.result_payload = {"field": field_key}
        action.status = "completed"
        return f"Saved — {field_key} updated."

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

    if action.action_type == "log_workout":
        workout_date = date.fromisoformat(payload["date"])
        sets = payload["sets"]
        session = await workout_service.create_workout(
            db, user.id, workout_date, sets
        )
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
