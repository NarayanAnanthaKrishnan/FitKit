"""Encrypted short-lived payloads and durable PostgreSQL queue primitives."""
import json
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import aliased

from api.config import settings
from api.models.db import DeliveryJob, TelegramUpdate

ACTIVE = ("received", "pending", "processing", "retry")
MAX_ATTEMPTS = 4


def encrypt(payload: dict) -> str:
    return Fernet(settings.queue_key.encode()).encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()


def decrypt(payload: str) -> dict:
    return json.loads(Fernet(settings.queue_key.encode()).decrypt(payload.encode()))


async def claim(db, model):
    now = datetime.now(timezone.utc)
    await db.execute(update(model).where(model.status == "processing", model.lease_until < now,
        model.attempts >= MAX_ATTEMPTS).values(status="failed", lease_token=None, lease_until=None, error_code="lease_attempts_exhausted"))
    older = aliased(model)
    if model is TelegramUpdate:
        same_user = older.telegram_user_id == model.telegram_user_id
        prior = or_(older.received_at < model.received_at, and_(older.received_at == model.received_at, older.update_id < model.update_id))
        ordering = (model.received_at, model.update_id)
    else:
        same_user = or_(older.user_id == model.user_id, older.update_id == model.update_id)
        prior = or_(older.created_at < model.created_at, and_(older.created_at == model.created_at,
            or_(older.sequence < model.sequence, and_(older.sequence == model.sequence, older.id < model.id))))
        ordering = (model.created_at, model.sequence, model.id)
    available = or_(model.status.in_(("received", "pending", "retry")), and_(model.status == "processing", model.lease_until < now))
    row = await db.scalar(select(model).where(
        available, model.attempts < MAX_ATTEMPTS, model.available_at <= now, model.encrypted_payload.is_not(None),
        ~exists(select(1).where(same_user, prior, older.status.in_(ACTIVE)))
    ).order_by(*ordering).limit(1).with_for_update(skip_locked=True))
    if row is None:
        return None
    row.status = "processing"
    row.attempts += 1
    row.lease_token = uuid.uuid4().hex
    row.lease_until = now + timedelta(seconds=60)
    await db.flush()
    return row


async def finish(db, model, key, lease_token: str, *, success: bool, error_code=None, retry_after=None):
    row = await db.get(model, key, with_for_update=True, populate_existing=True)
    if row is None or row.lease_token != lease_token or row.status != "processing":
        return
    now = datetime.now(timezone.utc)
    if success:
        row.status = "processed" if model is TelegramUpdate else "delivered"
        row.encrypted_payload = None
        row.error_code = None
        if model is TelegramUpdate:
            row.processed_at = now
    else:
        row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "retry"
        row.available_at = now + timedelta(seconds=max(1, retry_after or min(60, 2 ** row.attempts)))
        row.error_code = error_code or "processing_failed"
    row.lease_token = None
    row.lease_until = None


async def purge_payloads(db):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for model, created in ((TelegramUpdate, TelegramUpdate.received_at), (DeliveryJob, DeliveryJob.created_at)):
        await db.execute(update(model).where(created < cutoff, model.encrypted_payload.is_not(None)).values(
            encrypted_payload=None, status="expired", lease_token=None, lease_until=None, error_code="payload_expired"))
