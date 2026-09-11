import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import FitnessGoal
from api.commands import GoalCommand
from api.services.preferences_service import local_today
from api.services.audit_service import audit

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
    GoalCommand(goal_type=goal_type, target_value=target_value, unit=unit, target_date=target_date)
    today = await local_today(db, user_id)
    if target_date is not None and target_date < today:
        raise ValueError("Goal target date cannot be in the past.")
    goal = FitnessGoal(
        user_id=user_id,
        goal_type=goal_type,
        target_value=target_value,
        unit=unit,
        start_date=today,
        target_date=target_date,
        status="active",
    )
    db.add(goal)
    await db.flush()
    audit(db, user_id, "create_goal", {"goal_id": str(goal.id)})
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
    matches = [g for g in goals if str(g.id).startswith(ref)]
    return matches[0] if len(matches) == 1 else None


async def complete_goal(
    db: AsyncSession, user_id: uuid.UUID, goal_id: uuid.UUID
) -> FitnessGoal | None:
    goal = await _scoped_goal(db, user_id, goal_id)
    if goal is None:
        return None
    goal.status = "completed"
    audit(db, user_id, "complete_goal", {"goal_id": str(goal_id)})
    return goal


async def delete_goal(
    db: AsyncSession, user_id: uuid.UUID, goal_id: uuid.UUID
) -> bool:
    goal = await _scoped_goal(db, user_id, goal_id)
    if goal is None:
        return False
    await db.delete(goal)
    audit(db, user_id, "delete_goal", {"goal_id": str(goal_id)})
    return True


async def _scoped_goal(
    db: AsyncSession, user_id: uuid.UUID, goal_id: uuid.UUID
) -> FitnessGoal | None:
    return await db.scalar(
        select(FitnessGoal).where(
            FitnessGoal.id == goal_id, FitnessGoal.user_id == user_id
        )
    )
