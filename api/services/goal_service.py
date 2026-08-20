import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import FitnessGoal

GOAL_TYPE_WEIGHT = "weight"
GOAL_TYPE_FREQUENCY = "frequency"
GOAL_TYPES = {GOAL_TYPE_WEIGHT, GOAL_TYPE_FREQUENCY}


async def create_goal(
    db: AsyncSession,
    user_id: uuid.UUID,
    goal_type: str,
    target_value: float,
    unit: str,
    target_date: Optional[date] = None,
) -> FitnessGoal:
    goal = FitnessGoal(
        user_id=user_id,
        goal_type=goal_type,
        target_value=target_value,
        unit=unit,
        start_date=date.today(),
        target_date=target_date,
        status="active",
    )
    db.add(goal)
    await db.flush()
    return goal


async def list_goals(
    db: AsyncSession, user_id: uuid.UUID, status: Optional[str] = None
) -> list[FitnessGoal]:
    stmt = select(FitnessGoal).where(FitnessGoal.user_id == user_id)
    if status is not None:
        stmt = stmt.where(FitnessGoal.status == status)
    stmt = stmt.order_by(FitnessGoal.created_at.desc())
    return list((await db.scalars(stmt)).all())


async def get_goal_by_ref(
    db: AsyncSession, user_id: uuid.UUID, ref: str
) -> FitnessGoal | None:
    """Resolve a short opaque goal reference scoped to the user."""
    if not ref:
        return None
    goals = await list_goals(db, user_id)
    for goal in goals:
        if str(goal.id).startswith(ref):
            return goal
    return None


async def complete_goal(
    db: AsyncSession, user_id: uuid.UUID, goal_id: uuid.UUID
) -> FitnessGoal | None:
    goal = await _scoped_goal(db, user_id, goal_id)
    if goal is None:
        return None
    goal.status = "completed"
    return goal


async def delete_goal(
    db: AsyncSession, user_id: uuid.UUID, goal_id: uuid.UUID
) -> bool:
    goal = await _scoped_goal(db, user_id, goal_id)
    if goal is None:
        return False
    await db.delete(goal)
    return True


async def _scoped_goal(
    db: AsyncSession, user_id: uuid.UUID, goal_id: uuid.UUID
) -> FitnessGoal | None:
    return await db.scalar(
        select(FitnessGoal).where(
            FitnessGoal.id == goal_id, FitnessGoal.user_id == user_id
        )
    )
