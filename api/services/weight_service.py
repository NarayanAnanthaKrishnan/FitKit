import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import UserProfile, WeightMeasurement


async def record_weight(
    db: AsyncSession,
    user_id: uuid.UUID,
    weight_kg: float,
    measured_at: datetime,
    source: str = "telegram",
) -> float:
    """Store a weight measurement and update the profile snapshot.

    The profile snapshot is a convenience field; the measurement is the
    authoritative append-only history record.
    """
    user = await db.get(UserProfile, user_id)
    if user is None:
        raise ValueError("User not found")

    user.weight_kg = weight_kg
    db.add(
        WeightMeasurement(
            user_id=user_id,
            weight_kg=weight_kg,
            measured_at=measured_at,
            source=source,
        )
    )
    return weight_kg


async def get_weight_history(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 200
) -> list[WeightMeasurement]:
    """Return weight measurements, newest first."""
    rows = await db.scalars(
        select(WeightMeasurement)
        .where(WeightMeasurement.user_id == user_id)
        .order_by(
            WeightMeasurement.measured_at.desc(),
            WeightMeasurement.created_at.desc(),
        )
        .limit(limit)
    )
    return list(rows)
