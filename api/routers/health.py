from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import TelegramIdentity, UserProfile
from api.schemas import HealthSummaryResponse
from api.services.health_queries import get_recent_metric_readings

router = APIRouter(prefix="/health", tags=["health"])

HRV_BASELINE_DAYS = 7


def _latest_non_none(readings: list[float | None]) -> float | None:
    for value in reversed(readings):
        if value is not None:
            return value
    return None


def _mean_non_none(readings: list[float | None]) -> float | None:
    values = [v for v in readings if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


@router.get("/summary", response_model=HealthSummaryResponse)
async def health_summary(db: AsyncSession = Depends(get_db)):
    today = date.today()
    user = await db.scalar(select(UserProfile)
        .outerjoin(TelegramIdentity)
        .where(TelegramIdentity.id.is_(None))
        .limit(1))
    if user is None:
        return HealthSummaryResponse(as_of=today)

    hrv_7day = await get_recent_metric_readings(
        db, user.id, "hrv", HRV_BASELINE_DAYS
    )
    sleep_7day = await get_recent_metric_readings(
        db, user.id, "sleep_hours", HRV_BASELINE_DAYS
    )
    resting_7day = await get_recent_metric_readings(
        db, user.id, "resting_hr", HRV_BASELINE_DAYS
    )

    latest_hrv = _latest_non_none(hrv_7day)
    latest_sleep = _latest_non_none(sleep_7day)
    latest_resting = _latest_non_none(resting_7day)
    baseline = _mean_non_none(hrv_7day)

    return HealthSummaryResponse(
        latest_hrv=round(latest_hrv, 1) if latest_hrv is not None else None,
        latest_sleep_hours=(
            round(latest_sleep, 1) if latest_sleep is not None else None
        ),
        latest_resting_hr=(
            round(latest_resting, 1) if latest_resting is not None else None
        ),
        hrv_baseline_7day=round(baseline, 1) if baseline is not None else None,
        as_of=today,
    )
