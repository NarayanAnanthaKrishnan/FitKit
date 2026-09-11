"""Deterministic training recommendation for a user-scoped exercise.

The actual rule logic lives in ``engine/``; this service only gathers the
user's recent data and calls the engine, keeping the recommendation consistent
between the REST route and the Telegram adapter.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.models.db import ExerciseSet, WorkoutSession, ExerciseTarget
from api.services.preferences_service import local_today
from api.services.summary_service import health_snapshot
from engine.progression import suggested_load
from api.services.health_queries import get_recent_metric_readings
from engine.overload import SessionLog as EngineSessionLog, SetLog as EngineSetLog
from engine.recommend import (
    Recommendation,
    get_recommendation as engine_get_recommendation,
)
from engine.volume import DatedSet, compute_daily_volume

HISTORY_LIMIT = 5
VOLUME_LOOKBACK_DAYS = 28
RECOVERY_LOOKBACK_DAYS = 3
HRV_BASELINE_DAYS = 7
DEFAULT_TARGET_REPS = None


def _mean_or_none(readings: list[float | None]) -> float | None:
    values = [v for v in readings if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


async def get_recommendation(
    db: AsyncSession,
    user_id: uuid.UUID,
    exercise_name: str,
    target_reps: int | None = DEFAULT_TARGET_REPS,
    today: date | None = None,
) -> Recommendation:
    today = today or await local_today(db, user_id)
    target = await db.get(ExerciseTarget, (user_id, exercise_name))
    if target_reps is None and target is not None:
        target_reps = target.target_reps

    # Limit to sessions that actually contain the target exercise so a user
    # with many exercises cannot starve this exercise's history.
    session_rows = (
        await db.execute(
            select(WorkoutSession)
            .join(ExerciseSet, WorkoutSession.id == ExerciseSet.session_id)
            .where(
                WorkoutSession.user_id == user_id,
                ExerciseSet.exercise_name == exercise_name,
                WorkoutSession.date <= today,
            )
            .distinct()
            .order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc())
            .limit(HISTORY_LIMIT)
            .options(selectinload(WorkoutSession.sets))
        )
    ).scalars().all()

    exercise_history: list[EngineSessionLog] = []
    for s in reversed(session_rows):
        matching_sets = [
            es for es in s.sets if es.exercise_name == exercise_name
        ]
        if not matching_sets:
            continue
        exercise_history.append(
            EngineSessionLog(
                session_date=s.date,
                sets=[
                    EngineSetLog(
                        reps=es.reps, weight_kg=es.weight_kg, rpe=es.rpe
                    )
                    for es in sorted(matching_sets, key=lambda x: x.set_number)
                ],
            )
        )

    cutoff_volume = today - timedelta(days=VOLUME_LOOKBACK_DAYS)
    all_sets_rows = (
        await db.execute(
            select(WorkoutSession.date, ExerciseSet.reps, ExerciseSet.weight_kg)
            .join(ExerciseSet, WorkoutSession.id == ExerciseSet.session_id)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.date >= cutoff_volume,
                WorkoutSession.date <= today,
            )
        )
    ).all()

    dated_sets = [
        DatedSet(session_date=row.date, reps=row.reps, weight_kg=row.weight_kg)
        for row in all_sets_rows
    ]
    daily_volume = compute_daily_volume(dated_sets)

    hrv_readings = await get_recent_metric_readings(
        db, user_id, "hrv", RECOVERY_LOOKBACK_DAYS, today
    )
    sleep_readings = await get_recent_metric_readings(
        db, user_id, "sleep_hours", RECOVERY_LOOKBACK_DAYS, today
    )
    hrv_baseline_7day = _mean_or_none(
        await get_recent_metric_readings(db, user_id, "hrv", HRV_BASELINE_DAYS, today)
    )

    result = engine_get_recommendation(
        exercise_history=exercise_history,
        target_reps=target_reps,
        daily_volume=daily_volume,
        today=today,
        hrv_readings_last_3days=hrv_readings,
        hrv_baseline_7day=hrv_baseline_7day,
        sleep_readings_last_3days=sleep_readings,
    )
    result.as_of, result.target_reps = today, target_reps
    if target_reps is None:
        result.missing_inputs.append("target_reps")
    if len(exercise_history) < 3:
        result.missing_inputs.append("three_exercise_sessions")
    elif any(max(s.sets, key=lambda x: x.weight_kg).rpe is None for s in exercise_history[-3:]):
        result.missing_inputs.append("primary_set_rpe")
    result.reasons = [result.decision.value]
    if result.recovery_override:
        result.reasons.append(result.recovery_override)
    result.freshness = (await health_snapshot(db, user_id, today))["freshness"]
    result.suggested_load_kg = suggested_load(exercise_history, result.decision, target.load_increment_kg if target else None)
    return result
