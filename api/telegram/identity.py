from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import TelegramIdentity, UserProfile


async def get_or_create_identity(
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
