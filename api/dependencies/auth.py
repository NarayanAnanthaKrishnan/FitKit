import os
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import UserProfile
from api.services.user_scope import get_user_by_telegram_id


def secret_matches(received: Optional[str], expected: Optional[str]) -> bool:
    """Constant-time comparison so header checks cannot be timing-probed."""
    if not received or not expected:
        return False
    return secrets.compare_digest(
        received.encode("utf-8"), expected.encode("utf-8")
    )


async def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not secret_matches(x_api_key, os.environ.get("FITKIT_API_KEY")):
        raise HTTPException(status_code=401, detail="Invalid API key")


async def get_current_user(
    telegram_user_id: Optional[str] = Header(
        default=None, alias="X-Telegram-User-Id"
    ),
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    """Resolve the authenticated internal API context to a user-owned profile.

    This is an internal bridge for the current Health Auto Export/REST slice.
    The API key authenticates the calling application and the Telegram numeric
    ID selects an already-linked account. A future user-authentication layer
    can replace this dependency without changing domain services.
    """
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
