import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import (
    TelegramIdentity,
    TelegramUpdate,
    UserProfile,
    WeightMeasurement,
)
from api.services.user_data import delete_user_data

router = APIRouter(prefix="/integrations/telegram", tags=["telegram"])

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
_WEIGHT_PATTERN = re.compile(
    r"^\s*(?:i\s+weigh|weight\s*(?:is|:)?)?\s*"
    r"(\d+(?:\.\d+)?)\s*(kg|kgs|kilograms?|lb|lbs|pounds?)?\s*(?:today)?\s*$",
    re.IGNORECASE,
)


async def send_telegram_message(chat_id: int, text: str) -> None:
    """Send one text response through Telegram's Bot API."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        # Never propagate an exception containing the bot-token URL.
        raise RuntimeError("Telegram message delivery failed") from None
    if not payload.get("ok"):
        raise RuntimeError("Telegram message delivery failed")


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
    telegram_user_id = extracted[0] if extracted else None
    if not await _record_update_once(db, update_id, telegram_user_id):
        return {"ok": True, "duplicate": True}

    if extracted is None:
        await _mark_update(db, update_id, status="ignored")
        return {"ok": True, "ignored": True}

    telegram_user_id, chat_id, text, sender = extracted
    if not text:
        await _mark_update(db, update_id, status="ignored")
        return {"ok": True, "ignored": True}

    identity = await _get_or_create_identity(db, telegram_user_id, chat_id, sender)
    user = await db.get(UserProfile, identity.user_id)
    command = _command(text)

    if command == "/start":
        if user is not None and user.weight_kg is not None:
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
        await _mark_update(db, update_id)
        return {"ok": True}

    if command == "/help":
        await send_telegram_message(
            chat_id,
            "/start - start or resume setup\n"
            "/help - show this help\n"
            "/delete - permanently delete your FitKit data\n"
            "/cancel - cancel the current confirmation\n"
            "You can send a weight such as '75 kg' to record it.",
        )
        await _mark_update(db, update_id)
        return {"ok": True}

    if command == "/delete":
        identity.onboarding_step = "awaiting_delete_confirmation"
        await send_telegram_message(
            chat_id,
            "This will permanently delete your FitKit profile, weight history, "
            "workouts, and health data. This cannot be undone.\n\n"
            "Reply DELETE to confirm, or /cancel to keep your data.",
        )
        await _mark_update(db, update_id)
        return {"ok": True}

    if command == "/cancel":
        if identity.onboarding_step == "awaiting_delete_confirmation":
            identity.onboarding_step = (
                "complete" if user is not None and user.weight_kg is not None
                else "awaiting_weight"
            )
            await send_telegram_message(chat_id, "Deletion cancelled. Your data is safe.")
        else:
            await send_telegram_message(chat_id, "Nothing to cancel.")
        await _mark_update(db, update_id)
        return {"ok": True}

    if identity.onboarding_step == "awaiting_delete_confirmation":
        if text.upper() != "DELETE":
            await send_telegram_message(
                chat_id,
                "Deletion is still pending. Reply DELETE to confirm, or /cancel to keep your data.",
            )
            await _mark_update(db, update_id)
            return {"ok": True}

        if user is None:
            raise HTTPException(status_code=500, detail="Telegram user profile not found")
        await delete_user_data(
            db, user.id, current_update_id=update_id
        )
        await send_telegram_message(
            chat_id,
            "Your FitKit data has been permanently deleted. Send /start if you want to begin again.",
        )
        return {"ok": True}

    if identity.onboarding_step == "awaiting_weight":
        weight_kg = _parse_weight(text)
        if weight_kg is None:
            await send_telegram_message(
                chat_id,
                "Please send your current weight, for example: 80 kg or 176 lb.",
            )
            await _mark_update(db, update_id)
            return {"ok": True}
        if user is None:
            raise HTTPException(status_code=500, detail="Telegram user profile not found")
        user.weight_kg = weight_kg
        db.add(
            WeightMeasurement(
                user_id=user.id,
                weight_kg=weight_kg,
                measured_at=datetime.now(timezone.utc),
                source="telegram",
            )
        )
        identity.onboarding_step = "complete"
        await send_telegram_message(
            chat_id,
            f"Saved — your current weight is {weight_kg:.2f} kg. "
            "Your profile is ready. Send /help to continue.",
        )
        await _mark_update(db, update_id)
        return {"ok": True}

    weight_kg = _parse_weight(text)
    if weight_kg is not None:
        if user is None:
            raise HTTPException(status_code=500, detail="Telegram user profile not found")
        user.weight_kg = weight_kg
        db.add(
            WeightMeasurement(
                user_id=user.id,
                weight_kg=weight_kg,
                measured_at=datetime.now(timezone.utc),
                source="telegram",
            )
        )
        await send_telegram_message(
            chat_id,
            f"Saved — your current weight is {weight_kg:.2f} kg.",
        )
        await _mark_update(db, update_id)
        return {"ok": True}

    await send_telegram_message(
        chat_id,
        "I received your message. Send /help to see the available commands.",
    )
    await _mark_update(db, update_id)
    return {"ok": True}
