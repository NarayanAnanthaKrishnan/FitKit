from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import (
    ExerciseSet,
    HealthMetric,
    TelegramIdentity,
    TelegramUpdate,
    UserProfile,
    WeightMeasurement,
    WorkoutSession,
)


async def delete_user_data(
    db: AsyncSession,
    user_id: UUID,
    *,
    current_update_id: int | None = None,
) -> None:
    """Delete all registered user-owned data for an internal user ID.

    The optional update marker keeps Telegram deletion idempotent without
    allowing a retry to recreate the deleted identity. The service accepts
    internal ownership plus an idempotency key, never a Telegram payload.
    """
    telegram_user_id = await db.scalar(
        select(TelegramIdentity.telegram_user_id).where(
            TelegramIdentity.user_id == user_id
        )
    )
    session_ids = select(WorkoutSession.id).where(WorkoutSession.user_id == user_id)

    await db.execute(delete(ExerciseSet).where(ExerciseSet.session_id.in_(session_ids)))
    await db.execute(delete(WorkoutSession).where(WorkoutSession.user_id == user_id))
    await db.execute(delete(HealthMetric).where(HealthMetric.user_id == user_id))
    await db.execute(
        delete(WeightMeasurement).where(WeightMeasurement.user_id == user_id)
    )

    if telegram_user_id is not None:
        update_filter = TelegramUpdate.telegram_user_id == telegram_user_id
        if current_update_id is not None:
            update_filter = update_filter & (
                TelegramUpdate.update_id != current_update_id
            )
        await db.execute(delete(TelegramUpdate).where(update_filter))

    await db.execute(delete(TelegramIdentity).where(TelegramIdentity.user_id == user_id))
    await db.execute(delete(UserProfile).where(UserProfile.id == user_id))

    if current_update_id is not None:
        await db.execute(
            TelegramUpdate.__table__.update()
            .where(TelegramUpdate.update_id == current_update_id)
            .values(
                telegram_user_id=None,
                processed_at=func.now(),
                status="processed",
            )
        )
