from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db
from api.dependencies.auth import get_current_user
from api.models.db import UserProfile
from api.schemas import HealthSummaryResponse
from api.services.summary_service import health_snapshot

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/summary", response_model=HealthSummaryResponse)
async def health_summary(db: AsyncSession = Depends(get_db), user: UserProfile = Depends(get_current_user)):
    return await health_snapshot(db, user.id)
