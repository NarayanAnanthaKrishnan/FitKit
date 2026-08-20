import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies.auth import get_current_user
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import UserProfile
from api.schemas import (
    ExerciseHistoryResponse,
    SetResponse,
    WorkoutCreate,
    WorkoutResponse,
)
from api.services import workout_service

router = APIRouter(prefix="/workouts", tags=["workouts"])


def _set_response(db_set) -> SetResponse:
    return SetResponse(
        id=db_set.id,
        exercise_name=db_set.exercise_name,
        set_number=db_set.set_number,
        reps=db_set.reps,
        weight_kg=db_set.weight_kg,
        rpe=db_set.rpe,
        rest_seconds=db_set.rest_seconds,
        avg_heart_rate=db_set.avg_heart_rate,
    )


def _workout_response(session) -> WorkoutResponse:
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
        sets=[_set_response(s) for s in sorted(session.sets, key=lambda x: x.set_number)],
    )


@router.post("", response_model=WorkoutResponse, status_code=201)
async def create_workout(
    body: WorkoutCreate,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    sets = [s.model_dump() for s in body.sets]
    try:
        session = await workout_service.create_workout(
            db,
            user.id,
            body.date,
            sets,
            session_feeling_energy=body.session_feeling_energy,
            session_feeling_soreness=body.session_feeling_soreness,
            session_feeling_mood=body.session_feeling_mood,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _workout_response(session)


@router.get("/{exercise_name}/history", response_model=list[ExerciseHistoryResponse])
async def exercise_history(
    exercise_name: str,
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    if await workout_service.get_exercise(db, exercise_name) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown exercise: '{exercise_name}'",
        )

    sessions = await workout_service.exercise_history(
        db, user.id, exercise_name, limit
    )

    result = []
    for session in sessions:
        exercise_sets = [
            s for s in session.sets if s.exercise_name == exercise_name
        ]
        result.append(
            ExerciseHistoryResponse(
                session_id=session.id,
                session_date=session.date,
                sets=[
                    _set_response(s)
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
    session = await workout_service.get_workout(db, user.id, workout_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    return _workout_response(session)
