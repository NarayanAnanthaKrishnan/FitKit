"""Encrypted, expiring state for one natural-language follow-up at a time."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from api.models.db import ConversationState, InteractionEvent
from api.services import queue_service

STATE_TTL = timedelta(minutes=15)


async def _expire_row(db, row: ConversationState) -> None:
    try:
        payload = queue_service.decrypt(row.encrypted_payload)
        task_id = uuid.UUID(str(payload.get("task_id"))) if payload.get("task_id") else None
    except Exception:
        payload, task_id = {}, None
    if task_id is not None and row.kind in {"session_focus", "routine_planning", "routine_logging"}:
        db.add(InteractionEvent(
            user_id=row.user_id,
            route="local",
            intent="routine_logging" if row.kind == "routine_logging" else "routine_review",
            outcome="expired",
            reason_code="task_timeout",
            task_id=task_id,
            task_stage=str(payload.get("stage", ""))[:30] or None,
        ))
    await db.delete(row)
    await db.flush()


async def get_state(db, user_id) -> tuple[ConversationState | None, dict | None]:
    row = await db.get(ConversationState, user_id)
    if row is None:
        return None, None
    if row.expires_at <= datetime.now(timezone.utc):
        await _expire_row(db, row)
        return None, None
    try:
        payload = queue_service.decrypt(row.encrypted_payload)
    except Exception:
        await db.delete(row)
        await db.flush()
        return None, None
    return row, payload


async def set_state(db, user_id, kind: str, payload: dict) -> str:
    token = secrets.token_urlsafe(12)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    stmt = insert(ConversationState).values(
        user_id=user_id,
        kind=kind,
        encrypted_payload=queue_service.encrypt(payload),
        token_hash=token_hash,
        revision=1,
        expires_at=now + STATE_TTL,
        updated_at=now,
    )
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "kind": stmt.excluded.kind,
            "encrypted_payload": stmt.excluded.encrypted_payload,
            "token_hash": stmt.excluded.token_hash,
            "revision": ConversationState.revision + 1,
            "expires_at": stmt.excluded.expires_at,
            "updated_at": stmt.excluded.updated_at,
        },
    ))
    return token


async def clear_state(db, user_id) -> None:
    await db.execute(delete(ConversationState).where(ConversationState.user_id == user_id))


async def purge_expired(db) -> None:
    rows = (await db.scalars(select(ConversationState).where(
        ConversationState.expires_at <= datetime.now(timezone.utc)
    ))).all()
    for row in rows:
        await _expire_row(db, row)
