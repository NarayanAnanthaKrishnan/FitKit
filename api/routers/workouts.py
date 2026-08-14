import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies.auth import get_current_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from api.database import get_db
from api.models.db import (
    ExerciseSet,
    ExerciseTaxonomy,
    UserProfile,
    WorkoutSession,
)
from api.schemas import (
    ExerciseHistoryResponse,
    SetResponse,
    WorkoutCreate,
    WorkoutResponse,
)

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.post("", response_model=WorkoutResponse, status_code=201)
async def create_workout(
    body: WorkoutCreate,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    for s in body.sets:
        exercise = await db.get(ExerciseTaxonomy, s.exercise_name)
        if exercise is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown exercise: '{s.exercise_name}'",
            )

    session = WorkoutSession(
        user_id=user.id,
        date=body.date,
        session_feeling_energy=body.session_feeling_energy,
        session_feeling_soreness=",".join(body.session_feeling_soreness),
        session_feeling_mood=body.session_feeling_mood,
        watch_data_available=False,
    )
    db.add(session)
    await db.flush()

    db_sets = []
    for s in body.sets:
        db_set = ExerciseSet(
            session_id=session.id,
            exercise_name=s.exercise_name,
            set_number=s.set_number,
            reps=s.reps,
            weight_kg=s.weight_kg,
            rpe=s.rpe,
            rest_seconds=s.rest_seconds,
            avg_heart_rate=s.avg_heart_rate,
        )
        db.add(db_set)
        db_sets.append(db_set)
    await db.flush()

    return WorkoutResponse(
        id=session.id,
        user_id=session.user_id,
        date=session.date,
        session_feeling_energy=session.session_feeling_energy,
        session_feeling_soreness=(
            session.session_feeling_soreness.split(",")
            if session.session_feeling_soreness
            else []
        ),
        session_feeling_mood=session.session_feeling_mood,
        watch_data_available=session.watch_data_available,
        sets=[
            SetResponse(
                id=s.id,
                exercise_name=s.exercise_name,
                set_number=s.set_number,
                reps=s.reps,
                weight_kg=s.weight_kg,
                rpe=s.rpe,
                rest_seconds=s.rest_seconds,
                avg_heart_rate=s.avg_heart_rate,
            )
            for s in db_sets
        ],
    )


@router.get("/{exercise_name}/history", response_model=list[ExerciseHistoryResponse])
async def exercise_history(
    exercise_name: str,
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    exercise = await db.get(ExerciseTaxonomy, exercise_name)
    if exercise is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown exercise: '{exercise_name}'",
        )

    stmt = (
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user.id)
        .order_by(WorkoutSession.date.desc())
        .limit(limit)
        .options(selectinload(WorkoutSession.sets))
    )
    sessions = (await db.scalars(stmt)).all()

    result = []
    for session in sessions:
        exercise_sets = [s for s in session.sets if s.exercise_name == exercise_name]
        if not exercise_sets:
            continue
        result.append(
            ExerciseHistoryResponse(
                session_id=session.id,
                session_date=session.date,
                sets=[
                    SetResponse(
                        id=s.id,
                        exercise_name=s.exercise_name,
                        set_number=s.set_number,
                        reps=s.reps,
                        weight_kg=s.weight_kg,
                        rpe=s.rpe,
                        rest_seconds=s.rest_seconds,
                        avg_heart_rate=s.avg_heart_rate,
                    )
                    for s in sorted(exercise_sets, key=lambda x: x.set_number)
                ],
            )
        )
    return result


@router.get("/{workout_id}", response_model=WorkoutResponse)
async def get_workout(
    workout_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    stmt = (
        select(WorkoutSession)
        .where(
            WorkoutSession.id == workout_id,
            WorkoutSession.user_id == user.id,
        )
        .options(joinedload(WorkoutSession.sets))
    )
    session = (await db.scalars(stmt)).unique().first()
    if session is None:
        raise HTTPException(status_code=404, detail="Workout not found")

    return WorkoutResponse(
        id=session.id,
        user_id=session.user_id,
        date=session.date,
        session_feeling_energy=session.session_feeling_energy,
        session_feeling_soreness=(
            session.session_feeling_soreness.split(",")
            if session.session_feeling_soreness
            else []
        ),
        session_feeling_mood=session.session_feeling_mood,
        watch_data_available=session.watch_data_available,
        sets=[
            SetResponse(
                id=s.id,
                exercise_name=s.exercise_name,
                set_number=s.set_number,
                reps=s.reps,
                weight_kg=s.weight_kg,
                rpe=s.rpe,
                rest_seconds=s.rest_seconds,
                avg_heart_rate=s.avg_heart_rate,
            )
            for s in sorted(session.sets, key=lambda x: x.set_number)
        ],
    )
