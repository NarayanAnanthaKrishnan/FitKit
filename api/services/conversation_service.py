"""Encrypted, short-lived context for users who opted into natural conversation."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from api.models.db import ConversationTurn
from api.services import queue_service

RETENTION = timedelta(hours=24)
CONTEXT_TURNS = 6
MAX_STORED_TURNS = 12
MAX_CONTENT = 1000


async def recent_context(db, user_id, limit: int = CONTEXT_TURNS) -> list[dict[str, str]]:
    cutoff = datetime.now(timezone.utc) - RETENTION
    rows = (await db.scalars(
        select(ConversationTurn)
        .where(ConversationTurn.user_id == user_id, ConversationTurn.created_at >= cutoff)
        .order_by(
            ConversationTurn.created_at.desc(), ConversationTurn.turn_index.desc()
        ).limit(limit)
    )).all()
    turns = []
    for row in reversed(rows):
        try:
            content = queue_service.decrypt(row.encrypted_content).get("content")
        except Exception:
            continue
        if isinstance(content, str) and content:
            turns.append({"role": row.role, "content": content[:MAX_CONTENT]})
    return turns


async def remember_exchange(db, user_id, user_text: str, assistant_text: str, *, kind: str = "conversation") -> None:
    now = datetime.now(timezone.utc)
    await db.execute(delete(ConversationTurn).where(
        ConversationTurn.user_id == user_id,
        ConversationTurn.created_at < now - RETENTION,
    ))
    for turn_index, (role, content) in enumerate(
        (("user", user_text), ("assistant", assistant_text))
    ):
        db.add(ConversationTurn(
            user_id=user_id, role=role,
            kind=kind,
            turn_index=turn_index,
            encrypted_content=queue_service.encrypt({"content": content[:MAX_CONTENT]}),
        ))
    await db.flush()
    keep = select(ConversationTurn.id).where(ConversationTurn.user_id == user_id).order_by(
        ConversationTurn.created_at.desc(), ConversationTurn.turn_index.desc()
    ).limit(MAX_STORED_TURNS)
    await db.execute(delete(ConversationTurn).where(
        ConversationTurn.user_id == user_id,
        ConversationTurn.id.not_in(keep),
    ))


async def clear_context(db, user_id) -> None:
    await db.execute(delete(ConversationTurn).where(ConversationTurn.user_id == user_id))


async def purge_expired(db) -> None:
    await db.execute(delete(ConversationTurn).where(
        ConversationTurn.created_at < datetime.now(timezone.utc) - RETENTION
    ))
