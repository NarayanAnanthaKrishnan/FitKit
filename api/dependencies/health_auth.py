import os
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import UserProfile
from api.services.health_pairing_service import resolve_user_by_pairing
from api.services.user_scope import get_user_by_telegram_id


async def get_ingest_user(
    pairing_token: Optional[str] = Header(
        default=None, alias="X-Health-Pairing-Token"
    ),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    telegram_user_id: Optional[str] = Header(
        default=None, alias="X-Telegram-User-Id"
    ),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """Resolve the ingesting account from a per-user pairing token.

    The per-user opaque token is the primary credential. The legacy global
    API-key + Telegram-ID bridge remains only while
    ``ALLOW_LEGACY_INGEST_AUTH`` is enabled, for backwards compatibility
    during the pairing rollout.
    """
    if pairing_token:
        user = await resolve_user_by_pairing(db, pairing_token)
        if user is None:
            raise HTTPException(
                status_code=401, detail="Invalid or revoked pairing token"
            )
        return user

    if os.getenv("ALLOW_LEGACY_INGEST_AUTH", "1") != "1":
        raise HTTPException(
            status_code=401, detail="X-Health-Pairing-Token header is required"
        )

    expected = os.environ.get("FITKIT_API_KEY")
    if expected is None or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if telegram_user_id is None:
        raise HTTPException(
            status_code=401, detail="X-Telegram-User-Id header is required"
        )
    try:
        external_id = int(telegram_user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid Telegram user ID") from None
    if external_id <= 0:
        raise HTTPException(status_code=401, detail="Invalid Telegram user ID")

    user = await get_user_by_telegram_id(db, external_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Telegram user is not linked")
    return user
