from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import TelegramIdentity, UserProfile


async def get_user_by_telegram_id(
    db: AsyncSession, telegram_user_id: int
) -> UserProfile | None:
    """Resolve a Telegram external identity to its owned internal profile."""
    return await db.scalar(
        select(UserProfile)
        .join(TelegramIdentity, TelegramIdentity.user_id == UserProfile.id)
        .where(TelegramIdentity.telegram_user_id == telegram_user_id)
    )
