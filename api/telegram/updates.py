from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import TelegramUpdate


async def record_update_once(
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


async def mark_update(
    db: AsyncSession, update_id: int, status: str = "processed"
) -> None:
    await db.execute(
        TelegramUpdate.__table__.update()
        .where(TelegramUpdate.update_id == update_id)
        .values(processed_at=datetime.now(timezone.utc), status=status)
    )
