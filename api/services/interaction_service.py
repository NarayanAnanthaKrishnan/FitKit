"""Content-free conversation metrics and explicitly consented feedback."""
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from api.models.db import FeedbackSample, InteractionEvent
from api.services import queue_service

FEEDBACK_RETENTION = timedelta(days=30)


async def record_interaction(
    db, user_id, update_id: int | None, route: str, intent: str, outcome: str,
    *, reason_code: str | None = None, latency_ms: int | None = None,
    task_id: uuid.UUID | None = None, task_stage: str | None = None,
):
    values = dict(
        id=uuid.uuid4(), user_id=user_id, update_id=update_id, route=route,
        intent=intent, outcome=outcome, reason_code=reason_code,
        latency_ms=latency_ms, task_id=task_id, task_stage=task_stage,
    )
    stmt = insert(InteractionEvent).values(**values)
    if update_id is None:
        row = InteractionEvent(**values)
        db.add(row)
        await db.flush()
        return row.id
    else:
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["update_id"],
            set_={
                "route": stmt.excluded.route,
                "intent": stmt.excluded.intent,
                "outcome": stmt.excluded.outcome,
                "reason_code": stmt.excluded.reason_code,
                "latency_ms": stmt.excluded.latency_ms,
                "task_id": stmt.excluded.task_id,
                "task_stage": stmt.excluded.task_stage,
            },
        ))
        return await db.scalar(select(InteractionEvent.id).where(InteractionEvent.update_id == update_id))


async def rate_interaction(db, user_id, event_id, rating: str) -> bool:
    if rating not in {"up", "down"}:
        return False
    row = await db.scalar(select(InteractionEvent).where(
        InteractionEvent.id == event_id, InteractionEvent.user_id == user_id
    ).with_for_update())
    if row is None:
        return False
    row.rating = rating
    return True


async def save_feedback(db, user_id, content: str, event_id=None) -> FeedbackSample:
    text = " ".join((content or "").split())
    if not 1 <= len(text) <= 1000:
        raise ValueError("Feedback must be between 1 and 1000 characters")
    row = FeedbackSample(
        user_id=user_id,
        interaction_event_id=event_id,
        encrypted_content=queue_service.encrypt({"content": text}),
        expires_at=datetime.now(timezone.utc) + FEEDBACK_RETENTION,
    )
    db.add(row)
    await db.flush()
    return row


async def purge_expired(db) -> None:
    await db.execute(delete(FeedbackSample).where(
        FeedbackSample.expires_at <= datetime.now(timezone.utc)
    ))
