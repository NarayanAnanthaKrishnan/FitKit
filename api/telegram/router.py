"""FastAPI router — thin adapter, no business logic."""
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import UserProfile
from api.config import settings
from api.services.queue_service import encrypt
from api.models.db import TelegramUpdate
from api.telegram.constants import TELEGRAM_SECRET_HEADER
from api.telegram.dispatch import dispatch_message
from api.telegram.extract import extract_callback, extract_message
from api.telegram.handlers.common import telegram_secret_matches
from api.telegram.identity import get_or_create_identity
from api.telegram.updates import mark_update, record_update_once

router = APIRouter(prefix="/integrations/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(
    update: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    secret: str | None = Header(default=None, alias=TELEGRAM_SECRET_HEADER),
):
    if not telegram_secret_matches(secret):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    update_id = update.get("update_id")
    if type(update_id) is not int or not 0 <= update_id <= 2**63 - 1:
        raise HTTPException(status_code=400, detail="Telegram update_id is required")

    extracted = extract_message(update)
    callback = extract_callback(update)
    telegram_user_id = extracted[0] if extracted else (callback[0] if callback else None)
    if telegram_user_id is not None and settings.beta_user_ids and telegram_user_id not in settings.beta_user_ids:
        return {"ok": True, "ignored": True}
    if settings.production and not settings.beta_user_ids:
        raise HTTPException(status_code=503, detail="Beta access is not configured")
    if not await record_update_once(db, update_id, telegram_user_id):
        return {"ok": True, "duplicate": True}

    if extracted is None and callback is None:
        await mark_update(db, update_id, status="ignored")
        return {"ok": True, "ignored": True}

    if extracted is not None and not extracted[2]:
        await mark_update(db, update_id, status="ignored")
        return {"ok": True, "ignored": True}

    row = await db.get(TelegramUpdate, update_id)
    # Persist only the supported private message/callback, not arbitrary payload fields.
    row.encrypted_payload = encrypt({"message": list(extracted) if extracted else None,
                                     "callback": list(callback) if callback else None})
    await db.commit()  # Receipt is durable before returning success to Telegram.
    return {"ok": True}
