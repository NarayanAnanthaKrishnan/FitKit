"""AgentAction helpers — single place for pending-confirmation logic."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models.db import AgentAction, UserProfile, ExerciseTaxonomy
from api.commands import WeightCommand, WorkoutCommand, GoalCommand, TargetCommand
from api.services.preferences_service import local_today, validate_preference
from api.services.profile_service import validate_profile_field
from api.telegram.constants import DEFAULT_ACTION_TTL_SECONDS


def action_ttl_seconds() -> int:
    return settings.action_confirm_ttl_seconds


def action_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=action_ttl_seconds())


def not_expired() -> Any:
    return AgentAction.expires_at > datetime.now(timezone.utc)


async def validate_action(db, user_id, action_type, payload):
    if action_type == "record_weight":
        WeightCommand.model_validate(payload)
    elif action_type in {"log_workout", "correct_workout"}:
        parsed = WorkoutCommand.model_validate({"date": payload["date"], "sets": payload["sets"]})
        if parsed.date > await local_today(db, user_id):
            raise ValueError("A completed workout cannot be in the future.")
        names = {s.exercise_name for s in parsed.sets}
        found = set((await db.scalars(select(ExerciseTaxonomy.name).where(ExerciseTaxonomy.name.in_(names)))).all())
        if found != names:
            raise ValueError("Unknown exercise")
    elif action_type == "create_goal":
        parsed = GoalCommand.model_validate(payload)
        if parsed.target_date and parsed.target_date < await local_today(db, user_id):
            raise ValueError("Goal target date cannot be in the past.")
    elif action_type == "update_profile":
        _, error = validate_profile_field(payload["field"], str(payload["value"]))
        if error:
            raise ValueError(error)
    elif action_type == "set_preference":
        validate_preference(payload["field"], payload["value"])
    elif action_type == "set_target":
        TargetCommand.model_validate(payload)
    elif action_type == "remember_preference":
        from api.services.memory_service import validate_proposal
        validate_proposal(payload)
    elif action_type == "clear_memories":
        if payload not in ({}, None):
            raise ValueError("Memory clearing does not accept details")
    elif action_type not in {"delete_goal", "delete_user"}:
        raise ValueError("Unknown action type.")


async def record_agent_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    action_type: str,
    input_payload: dict,
    status: str = "pending_confirmation",
    confirmation_token: str | None = None,
) -> AgentAction:
    await validate_action(db, user_id, action_type, input_payload)
    # Serialize preview replacement even when two different updates arrive together.
    await db.scalar(select(UserProfile.id).where(UserProfile.id == user_id).with_for_update())
    if status == "pending_confirmation":
        await db.execute(update(AgentAction).where(AgentAction.user_id == user_id, AgentAction.status == "pending_confirmation").values(status="superseded", confirmation_token=None, pending_edit_field=None))
    action = AgentAction(
        user_id=user_id,
        action_type=action_type,
        input_payload=input_payload,
        status=status,
        confirmation_token=confirmation_token,
        expires_at=action_expiry() if status == "pending_confirmation" else None,
    )
    db.add(action)
    await db.flush()
    return action


async def pending_action(
    db: AsyncSession, user_id: uuid.UUID, token: str
) -> AgentAction | None:
    await db.scalar(select(UserProfile.id).where(UserProfile.id == user_id).with_for_update())
    return await db.scalar(
        select(AgentAction).where(
            AgentAction.user_id == user_id,
            AgentAction.confirmation_token == token,
            AgentAction.status == "pending_confirmation",
            not_expired(),
        ).with_for_update().execution_options(populate_existing=True)
    )


async def pending_edit_action(
    db: AsyncSession, user_id: uuid.UUID
) -> AgentAction | None:
    return await db.scalar(
        select(AgentAction)
        .where(
            AgentAction.user_id == user_id,
            AgentAction.status == "pending_confirmation",
            AgentAction.pending_edit_field.is_not(None),
            not_expired(),
        )
        .order_by(AgentAction.created_at.desc())
        .limit(1)
        .with_for_update()
    )
