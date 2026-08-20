import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.models.db import FitnessGoal, UserProfile, WorkoutSession
from api.services.goal_service import list_goals
from api.services.health_queries import get_recent_metric_readings
from api.services.weight_service import get_weight_history

HRV_BASELINE_DAYS = 7
_WEIGHT_LB_PER_KG = 0.45359237


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


async def health_snapshot(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Latest recovery readings plus a 7-day HRV baseline."""
    hrv = await get_recent_metric_readings(db, user_id, "hrv", HRV_BASELINE_DAYS)
    sleep = await get_recent_metric_readings(
        db, user_id, "sleep_hours", HRV_BASELINE_DAYS
    )
    resting = await get_recent_metric_readings(
        db, user_id, "resting_hr", HRV_BASELINE_DAYS
    )
    latest_hrv = _latest_non_none(hrv)
    latest_sleep = _latest_non_none(sleep)
    latest_resting = _latest_non_none(resting)
    baseline = _mean_non_none(hrv)
    return {
        "latest_hrv": round(latest_hrv, 1) if latest_hrv is not None else None,
        "latest_sleep_hours": (
            round(latest_sleep, 1) if latest_sleep is not None else None
        ),
        "latest_resting_hr": (
            round(latest_resting, 1) if latest_resting is not None else None
        ),
        "hrv_baseline_7day": round(baseline, 1) if baseline is not None else None,
        "has_data": (
            latest_hrv is not None
            or latest_sleep is not None
            or latest_resting is not None
        ),
    }


async def today_snapshot(db: AsyncSession, user_id: uuid.UUID) -> dict:
    profile = await db.get(UserProfile, user_id)
    health = await health_snapshot(db, user_id)
    last_workout = await _last_workout(db, user_id)
    return {
        "weight_kg": profile.weight_kg if profile is not None else None,
        "health": health,
        "last_workout": last_workout,
    }


async def progress_summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    weight = await _weight_trend(db, user_id)
    goals = await list_goals(db, user_id, status="active")
    goal_rows = [await _goal_progress(db, user_id, g) for g in goals]
    return {"weight": weight, "goals": goal_rows}


async def _last_workout(db: AsyncSession, user_id: uuid.UUID) -> dict | None:
    session = await db.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user_id)
        .order_by(WorkoutSession.date.desc())
        .limit(1)
        .options(selectinload(WorkoutSession.sets))
    )
    if session is None:
        return None
    exercises = sorted({s.exercise_name for s in session.sets})
    return {"date": session.date, "exercises": exercises}


async def _weight_trend(db: AsyncSession, user_id: uuid.UUID) -> dict:
    history = await get_weight_history(db, user_id, limit=200)
    if not history:
        return {"latest_kg": None, "change_7d": None, "change_30d": None}
    ascending = list(reversed(history))  # oldest first
    latest = ascending[-1]
    latest_date = latest.measured_at.date()
    return {
        "latest_kg": latest.weight_kg,
        "change_7d": _change_since(ascending, latest_date, 7),
        "change_30d": _change_since(ascending, latest_date, 30),
    }


def _change_since(ascending, latest_date: date, days: int) -> float | None:
    cutoff = latest_date - timedelta(days=days)
    baseline = None
    for measurement in ascending:
        if measurement.measured_at.date() <= cutoff:
            baseline = measurement.weight_kg
    if baseline is None:
        return None
    return round(ascending[-1].weight_kg - baseline, 1)


async def _goal_progress(
    db: AsyncSession, user_id: uuid.UUID, goal: FitnessGoal
) -> dict:
    ref = str(goal.id)[:8]
    if goal.goal_type == "frequency":
        current = await _session_count_since(db, user_id, goal.start_date)
        target = goal.target_value
        progress_pct = (
            round(min(100.0, current / target * 100)) if target else None
        )
        return {
            "ref": ref,
            "type": "frequency",
            "current": current,
            "target": target,
            "unit": goal.unit,
            "progress_pct": progress_pct,
            "status": goal.status,
        }

    profile = await db.get(UserProfile, user_id)
    current_kg = profile.weight_kg if profile is not None else None
    current = current_kg
    if goal.unit == "lb" and current_kg is not None:
        current = round(current_kg / _WEIGHT_LB_PER_KG, 1)
    return {
        "ref": ref,
        "type": "weight",
        "current": current,
        "target": goal.target_value,
        "unit": goal.unit,
        "progress_pct": None,
        "status": goal.status,
    }


async def _session_count_since(
    db: AsyncSession, user_id: uuid.UUID, start_date: date
) -> int:
    count = await db.scalar(
        select(func.count(WorkoutSession.id)).where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.date >= start_date,
        )
    )
    return int(count or 0)
