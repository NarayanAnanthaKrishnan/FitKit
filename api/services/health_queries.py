import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import HealthMetric


async def get_recent_metric_readings(
    db: AsyncSession,
    user_id: uuid.UUID,
    metric_type: str,
    days: int,
    today: date | None = None,
) -> list[float | None]:
    """Returns `days` most-recent daily values, oldest first, missing days as None.

    Daily value = average of all readings for that calendar day. `today` defaults
    to the current date and is overridable for deterministic tests.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=days - 1)

    rows = (
        await db.execute(
            select(func.date(HealthMetric.timestamp), func.avg(HealthMetric.value))
            .where(
                HealthMetric.user_id == user_id,
                HealthMetric.metric_type == metric_type,
                HealthMetric.timestamp >= cutoff,
            )
            .group_by(func.date(HealthMetric.timestamp))
            .order_by(func.date(HealthMetric.timestamp))
        )
    ).all()

    day_values: dict[date, float] = {row[0]: row[1] for row in rows}
    return [
        day_values.get(today - timedelta(days=i))
        for i in range(days - 1, -1, -1)
    ]
