import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import UserProfile, WeightMeasurement
from api.commands import WeightCommand
from api.services.audit_service import audit


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
    WeightCommand(weight_kg=weight_kg, measured_at=measured_at)
    if measured_at.tzinfo is None or measured_at > datetime.now(timezone.utc):
        raise ValueError("Weight time must include a timezone and cannot be in the future.")
    user = await db.scalar(select(UserProfile).where(UserProfile.id == user_id).with_for_update())
    if user is None:
        raise ValueError("User not found")

    latest = await db.scalar(select(WeightMeasurement).where(WeightMeasurement.user_id == user_id).order_by(WeightMeasurement.measured_at.desc(), WeightMeasurement.created_at.desc()).limit(1))
    if latest is None or measured_at >= latest.measured_at:
        user.weight_kg = weight_kg
    db.add(
        WeightMeasurement(
            user_id=user_id,
            weight_kg=weight_kg,
            measured_at=measured_at,
            source=source,
        )
    )
    audit(db, user_id, "record_weight", {"source": source})
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
