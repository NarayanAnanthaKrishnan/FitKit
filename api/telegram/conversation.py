"""Tiny conversation hint builder — no history dump, no secrets."""
from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import AgentAction, TelegramIdentity, UserProfile


async def build_context_hint(
    db: AsyncSession, user_id: uuid.UUID, identity: TelegramIdentity, user: UserProfile
) -> dict:
    """Return minimal context for LLM — safe to send to gateway."""
    # pending action type for yes/no disambiguation
    pending = await db.scalar(
        select(AgentAction.action_type).where(
            AgentAction.user_id == user_id,
            AgentAction.status == "pending_confirmation",
        ).order_by(AgentAction.created_at.desc()).limit(1)
    )
    # what profile field is still missing -> helps "23" -> age
    missing = []
    if user.age is None:
        missing.append("age")
    if user.sex is None:
        missing.append("sex")
    if user.resting_hr is None:
        missing.append("resting_hr")
    profile_context = None
    if missing:
        profile_context = f"missing: {','.join(missing[:3])}"
    hint: dict = {}
    if pending:
        hint["pending_action_type"] = pending
    if identity.onboarding_step:
        hint["pending_onboarding_step"] = identity.onboarding_step
    if profile_context:
        hint["profile_context"] = profile_context
    # short preview of pending payload for LLM to not ask again
    if pending:
        act = await db.scalar(
            select(AgentAction).where(
                AgentAction.user_id == user_id,
                AgentAction.status == "pending_confirmation",
            ).order_by(AgentAction.created_at.desc()).limit(1)
        )
        if act and act.input_payload:
            # keep tiny
            payload = act.input_payload
            if act.action_type == "update_profile":
                hint["pending_preview"] = f"{payload.get('field')}->{payload.get('value')}"
            elif act.action_type == "record_weight":
                hint["pending_preview"] = f"weight->{payload.get('weight_kg')}"
    return hint
