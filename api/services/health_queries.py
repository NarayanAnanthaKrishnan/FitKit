import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import HealthMetric
from api.services.preferences_service import get_preferences, local_today, day_bounds


async def metric_series(
    db: AsyncSession,
    user_id: uuid.UUID,
    metric_type: str,
    days: int,
    today: date | None = None,
) -> list[dict]:
    """Daily values and provenance. Conflicting sources/totals remain missing.

    HRV and resting HR use the daily mean from one source. Sleep ingestion
    accepts daily totals; differing totals cannot safely be averaged or summed.
    """
    today = today or await local_today(db, user_id)
    prefs = await get_preferences(db, user_id)
    cutoff = today - timedelta(days=days - 1)
    start, _ = day_bounds(cutoff, prefs.timezone)
    _, end = day_bounds(today, prefs.timezone)
    local_day = func.date(func.timezone(prefs.timezone, HealthMetric.timestamp))

    rows = (
        await db.execute(
            select(local_day, func.avg(HealthMetric.value), func.min(HealthMetric.value), func.max(HealthMetric.value),
                   func.max(HealthMetric.timestamp), func.array_agg(func.distinct(HealthMetric.source)))
            .where(
                HealthMetric.user_id == user_id,
                HealthMetric.metric_type == metric_type,
                HealthMetric.timestamp >= start,
                HealthMetric.timestamp < end,
            )
            .group_by(local_day)
            .order_by(local_day)
        )
    ).all()

    day_values = {}
    for day, mean, low, high, measured_at, sources in rows:
        conflict = len(sources) > 1 or (metric_type == "sleep_hours" and low != high)
        day_values[day] = {"value": None if conflict else mean, "measured_at": measured_at,
                           "sources": sorted(sources), "conflict": conflict}
    return [day_values.get(today - timedelta(days=i), {"value": None, "measured_at": None, "sources": [], "conflict": False}) for i in range(days - 1, -1, -1)]


async def get_recent_metric_readings(db, user_id, metric_type, days, today=None) -> list[float | None]:
    return [row["value"] for row in await metric_series(db, user_id, metric_type, days, today)]
