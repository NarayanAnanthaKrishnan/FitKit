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

from api.models.db import ExerciseSet, WorkoutSession
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
DEFAULT_TARGET_REPS = 8


def _mean_or_none(readings: list[float | None]) -> float | None:
    values = [v for v in readings if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


async def get_recommendation(
    db: AsyncSession,
    user_id: uuid.UUID,
    exercise_name: str,
    target_reps: int = DEFAULT_TARGET_REPS,
    today: date | None = None,
) -> Recommendation:
    today = today or date.today()

    # Limit to sessions that actually contain the target exercise so a user
    # with many exercises cannot starve this exercise's history.
    session_rows = (
        await db.execute(
            select(WorkoutSession)
            .join(ExerciseSet, WorkoutSession.id == ExerciseSet.session_id)
            .where(
                WorkoutSession.user_id == user_id,
                ExerciseSet.exercise_name == exercise_name,
            )
            .distinct()
            .order_by(WorkoutSession.date.desc())
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
            )
        )
    ).all()

    dated_sets = [
        DatedSet(session_date=row.date, reps=row.reps, weight_kg=row.weight_kg)
        for row in all_sets_rows
    ]
    daily_volume = compute_daily_volume(dated_sets)

    hrv_readings = await get_recent_metric_readings(
        db, user_id, "hrv", RECOVERY_LOOKBACK_DAYS
    )
    sleep_readings = await get_recent_metric_readings(
        db, user_id, "sleep_hours", RECOVERY_LOOKBACK_DAYS
    )
    hrv_baseline_7day = _mean_or_none(
        await get_recent_metric_readings(db, user_id, "hrv", HRV_BASELINE_DAYS)
    )

    return engine_get_recommendation(
        exercise_history=exercise_history,
        target_reps=target_reps,
        daily_volume=daily_volume,
        today=today,
        hrv_readings_last_3days=hrv_readings,
        hrv_baseline_7day=hrv_baseline_7day,
        sleep_readings_last_3days=sleep_readings,
    )
