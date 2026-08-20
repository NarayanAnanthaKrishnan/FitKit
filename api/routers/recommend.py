from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies.auth import get_current_user
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import UserProfile
from api.schemas import RecommendationResponse
from api.services import recommendation_service, workout_service

router = APIRouter(prefix="/recommend", tags=["recommend"])


@router.get("/{exercise_name}", response_model=RecommendationResponse)
async def recommend(
    exercise_name: str,
    target_reps: int = Query(default=recommendation_service.DEFAULT_TARGET_REPS, ge=1),
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    if await workout_service.get_exercise(db, exercise_name) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown exercise: '{exercise_name}'",
        )

    result = await recommendation_service.get_recommendation(
        db, user.id, exercise_name, target_reps
    )

    return RecommendationResponse(
        decision=result.decision.value,
        acwr_ratio=result.acwr_ratio,
        acwr_flag=result.acwr_flag,
        recovery_override=result.recovery_override,
        explanation=result.explanation,
    )
