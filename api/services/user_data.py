from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import (
    AgentAction,
    DashboardLink,
    ExerciseSet,
    FitnessGoal,
    HealthMetric,
    HealthPairing,
    TelegramIdentity,
    TelegramUpdate,
    UserProfile,
    WeightMeasurement,
    WorkoutSession,
    DeliveryJob,
    LLMUsage,
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
    await db.scalar(select(UserProfile.id).where(UserProfile.id == user_id).with_for_update())
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
    await db.execute(delete(FitnessGoal).where(FitnessGoal.user_id == user_id))
    await db.execute(delete(AgentAction).where(AgentAction.user_id == user_id))
    await db.execute(delete(HealthPairing).where(HealthPairing.user_id == user_id))
    await db.execute(delete(DashboardLink).where(DashboardLink.user_id == user_id))
    await db.execute(delete(DeliveryJob).where(DeliveryJob.user_id == user_id))
    await db.execute(delete(LLMUsage).where(LLMUsage.scope == str(user_id)))

    if telegram_user_id is not None:
        update_filter = TelegramUpdate.telegram_user_id == telegram_user_id
        if current_update_id is not None:
            update_filter = update_filter & (
                TelegramUpdate.update_id != current_update_id
            )
        await db.execute(update(TelegramUpdate).where(update_filter).values(telegram_user_id=None,
            encrypted_payload=None, status="cancelled", lease_token=None, lease_until=None))

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
                encrypted_payload=None,
            )
        )
