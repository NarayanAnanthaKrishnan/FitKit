import uuid
from datetime import date, timedelta, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.models.db import FitnessGoal, UserProfile, WorkoutSession, HealthMetric, ExerciseSet
from api.services.preferences_service import local_today, get_preferences, day_bounds
from engine.one_rm import epley_1rm
from api.services.goal_service import list_goals
from api.services.health_queries import get_recent_metric_readings, metric_series
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


async def health_snapshot(db: AsyncSession, user_id: uuid.UUID, today: date | None = None) -> dict:
    """Latest recovery readings plus a 7-day HRV baseline."""
    today = today or await local_today(db, user_id)
    prefs = await get_preferences(db, user_id)
    series = {kind: await metric_series(db, user_id, kind, HRV_BASELINE_DAYS, today) for kind in ("hrv", "sleep_hours", "resting_hr")}
    hrv, sleep, resting = ([r["value"] for r in series[kind]] for kind in ("hrv", "sleep_hours", "resting_hr"))
    latest_hrv = _latest_non_none(hrv)
    latest_sleep = _latest_non_none(sleep)
    latest_resting = _latest_non_none(resting)
    baseline = _mean_non_none(hrv)
    _, end = day_bounds(today, prefs.timezone)
    freshness = {}
    for kind, rows in series.items():
        usable = next((row for row in reversed(rows) if row["value"] is not None), None)
        conflict = any(row["conflict"] for row in rows)
        if usable or conflict:
            stamp = usable["measured_at"] if usable else None
            freshness[kind] = {"measured_at": stamp.isoformat() if stamp else None,
                               "stale": stamp is None or stamp < end - timedelta(hours=48),
                               "sources": usable["sources"] if usable else [], "conflicting_days": sum(row["conflict"] for row in rows)}
    return {
        "as_of": today,
        "timezone": prefs.timezone,
        "freshness": freshness,
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
        "units": (await get_preferences(db, user_id)).units,
        "as_of": health["as_of"],
        "timezone": health["timezone"],
        "weight_kg": profile.weight_kg if profile is not None else None,
        "health": health,
        "last_workout": last_workout,
    }


async def progress_summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    weight = await _weight_trend(db, user_id)
    weight["units"] = (await get_preferences(db, user_id)).units
    goals = await list_goals(db, user_id, status="active")
    goal_rows = [await _goal_progress(db, user_id, g) for g in goals]
    today = await local_today(db, user_id)
    weekly = []
    for weeks_ago in range(3, -1, -1):
        start = today - timedelta(days=today.weekday(), weeks=weeks_ago)
        count = await db.scalar(select(func.count(WorkoutSession.id)).where(WorkoutSession.user_id == user_id, WorkoutSession.date >= start, WorkoutSession.date <= min(today, start + timedelta(days=6))))
        weekly.append({"week_start": start.isoformat(), "sessions": int(count or 0)})
    rows = (await db.execute(select(ExerciseSet.exercise_name, ExerciseSet.reps, ExerciseSet.weight_kg, WorkoutSession.date, WorkoutSession.id)
        .join(WorkoutSession, WorkoutSession.id == ExerciseSet.session_id).where(WorkoutSession.user_id == user_id,
            WorkoutSession.date <= today, WorkoutSession.date >= today - timedelta(days=28)).order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc(), ExerciseSet.set_number))).all()
    exercises = {}
    for name, reps, load, workout_date, workout_id in rows:
        entry = exercises.setdefault(name, {"exercise_name": name, "latest_date": workout_date.isoformat(), "workout_id": str(workout_id), "best_estimated_1rm_kg": None})
        if load > 0 and reps <= 12:
            estimate = epley_1rm(load, reps)
            entry["best_estimated_1rm_kg"] = max(entry["best_estimated_1rm_kg"] or 0, estimate)
    return {"weight": weight, "goals": goal_rows, "weekly_sessions": weekly, "exercises": list(exercises.values()), "as_of": today}


async def _last_workout(db: AsyncSession, user_id: uuid.UUID) -> dict | None:
    session = await db.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user_id)
        .where(WorkoutSession.date <= await local_today(db, user_id))
        .order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc())
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
        today = await local_today(db, user_id)
        start = max(goal.start_date, today - timedelta(days=today.weekday()))
        current = await _session_count_since(db, user_id, start, today)
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
    db: AsyncSession, user_id: uuid.UUID, start_date: date, end_date: date
) -> int:
    count = await db.scalar(
        select(func.count(WorkoutSession.id)).where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.date >= start_date,
            WorkoutSession.date <= end_date,
        )
    )
    return int(count or 0)
