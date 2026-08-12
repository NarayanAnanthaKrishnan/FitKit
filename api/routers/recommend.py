from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.database import get_db
from api.models.db import (
    ExerciseSet,
    ExerciseTaxonomy,
    TelegramIdentity,
    UserProfile,
    WorkoutSession,
)
from api.schemas import RecommendationResponse
from api.services.health_queries import get_recent_metric_readings
from engine.overload import SessionLog as EngineSessionLog, SetLog as EngineSetLog
from engine.recommend import get_recommendation
from engine.volume import DatedSet, compute_daily_volume

router = APIRouter(prefix="/recommend", tags=["recommend"])

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


@router.get("/{exercise_name}", response_model=RecommendationResponse)
async def recommend(
    exercise_name: str,
    target_reps: int = Query(default=DEFAULT_TARGET_REPS, ge=1),
    db: AsyncSession = Depends(get_db),
):
    exercise = await db.get(ExerciseTaxonomy, exercise_name)
    if exercise is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown exercise: '{exercise_name}'",
        )

    user = await db.scalar(select(UserProfile)
        .outerjoin(TelegramIdentity)
        .where(TelegramIdentity.id.is_(None))
        .limit(1))
    today = date.today()

    if user is None:
        return RecommendationResponse(
            decision="insufficient_data",
            acwr_ratio=None,
            acwr_flag="insufficient_data",
            recovery_override=None,
            explanation="No user profile found",
        )

    session_rows = (
        await db.execute(
            select(WorkoutSession)
            .where(WorkoutSession.user_id == user.id)
            .order_by(WorkoutSession.date.desc())
            .limit(HISTORY_LIMIT)
            .options(selectinload(WorkoutSession.sets))
        )
    ).scalars().all()

    exercise_history = []
    for s in reversed(session_rows):
        matching_sets = [es for es in s.sets if es.exercise_name == exercise_name]
        if not matching_sets:
            continue
        exercise_history.append(
            EngineSessionLog(
                session_date=s.date,
                sets=[
                    EngineSetLog(reps=es.reps, weight_kg=es.weight_kg, rpe=es.rpe)
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
                WorkoutSession.user_id == user.id,
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
        db, user.id, "hrv", RECOVERY_LOOKBACK_DAYS
    )
    sleep_readings = await get_recent_metric_readings(
        db, user.id, "sleep_hours", RECOVERY_LOOKBACK_DAYS
    )
    hrv_baseline_7day = _mean_or_none(
        await get_recent_metric_readings(db, user.id, "hrv", HRV_BASELINE_DAYS)
    )

    result = get_recommendation(
        exercise_history=exercise_history,
        target_reps=target_reps,
        daily_volume=daily_volume,
        today=today,
        hrv_readings_last_3days=hrv_readings,
        hrv_baseline_7day=hrv_baseline_7day,
        sleep_readings_last_3days=sleep_readings,
    )

    return RecommendationResponse(
        decision=result.decision.value,
        acwr_ratio=result.acwr_ratio,
        acwr_flag=result.acwr_flag,
        recovery_override=result.recovery_override,
        explanation=result.explanation,
    )