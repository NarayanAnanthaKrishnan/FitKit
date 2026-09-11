"""Minimal mutation audit; no raw incoming message or health payload."""
from sqlalchemy.ext.asyncio import AsyncSession
from api.models.db import AgentAction


def audit(db: AsyncSession, user_id, action_type: str, result: dict, *, status="completed") -> None:
    db.add(AgentAction(user_id=user_id, action_type=action_type, input_payload={}, result_payload=result, status=status))
