"""Run with python -m api.worker. No outbound network calls occur in domain transactions."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from api.config import settings
from api.security import configure_logging
configure_logging()
from api.database import async_session_factory
from api.llm import gateway
from api.models.db import AgentAction, ConversationState, DeliveryJob, TelegramIdentity, TelegramUpdate, UserProfile, WorkerHeartbeat
from api.services import queue_service, telegram_client
from api.services import conversation_service, conversation_state_service, interaction_service
from api.services.agent_context_service import build_agent_context
from api.services.audit_service import audit
from api.services.preferences_service import get_preferences
from api.telegram.agent_actions import not_expired
from api.telegram.callbacks import handle_callback
from api.telegram.client import outbound_context
from api.telegram.dispatch import dispatch_message
from api.telegram.identity import get_or_create_identity
from api.telegram.interpretation import prepared_interpretation
from api.telegram.natural import classify_natural

logger = logging.getLogger(__name__)


async def prepare(payload, session_factory):
    message = payload.get("message")
    if not message or not gateway.is_llm_enabled():
        return None
    external_id, _, text, _ = message
    if text.startswith("/"):
        return None
    async with session_factory() as db:
        identity = await db.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == external_id))
        if identity is None:
            return None
        prefs = await get_preferences(db, identity.user_id)
        if not prefs.ai_enabled:
            return None
        pending = await db.scalar(select(AgentAction.id).where(AgentAction.user_id == identity.user_id, AgentAction.status == "pending_confirmation", not_expired()).limit(1))
        if pending is not None:
            return None
        active_state = await db.scalar(select(ConversationState.kind).where(
            ConversationState.user_id == identity.user_id,
            ConversationState.expires_at > datetime.now(timezone.utc),
        ))
        if active_state in {"feedback_note", "feedback_review", "workout_missing_load"}:
            return None
        context = await build_agent_context(db, identity, identity.user_id)
        user_id = identity.user_id
    from api.services.llm_usage_service import reserve_attempt

    async def reserve():
        return await reserve_attempt(session_factory, user_id)
    # The read session has closed. The gateway's usage reservations have their
    # own short transactions and are charged even if interpretation fails.
    local = classify_natural(text) if settings.conversation_v2 else None
    if local is not None:
        # High-confidence local intents already have reviewed conversational
        # replies. Avoid spending latency and budget merely to add an opener.
        return None
    return await gateway.interpret_free_text(text, user_id=user_id, context=context, reserve=reserve)


async def process_one(session_factory=async_session_factory):
    async with session_factory() as db:
        job = await queue_service.claim(db, TelegramUpdate)
        if job is None:
            await db.commit()  # Persist exhausted-lease maintenance too.
            return False
        key, lease, ciphertext = job.update_id, job.lease_token, job.encrypted_payload
        await db.commit()
    try:
        payload = queue_service.decrypt(ciphertext)
        interpretation = await prepare(payload, session_factory)
        async with session_factory() as db:
            job = await db.get(TelegramUpdate, key, with_for_update=True)
            if job is None or job.lease_token != lease or job.status != "processing" or job.lease_until < datetime.now(timezone.utc):
                return True
            data = payload.get("callback") or payload["message"]
            external_id, chat_id = data[:2]
            sender = data[3]
            if payload.get("callback"):
                identity = await db.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == external_id))
                if identity is None:
                    await queue_service.finish(db, TelegramUpdate, key, lease, success=True)
                    await db.commit()
                    return True
            else:
                identity = await get_or_create_identity(db, external_id, chat_id, sender)
            user = await db.scalar(select(UserProfile).where(UserProfile.id == identity.user_id).with_for_update())
            # Recheck opt-in in the write transaction. Consent may have changed
            # while a provider call was in flight.
            prefs = await get_preferences(db, user.id)
            if not prefs.ai_enabled:
                interpretation = None
            if interpretation is not None and interpretation.fallback:
                audit(
                    db,
                    user.id,
                    "interpret_message",
                    {"code": interpretation.error or "provider_fallback"},
                    status="fallback",
                )
            with outbound_context(db, user.id, key), prepared_interpretation(interpretation):
                if payload.get("callback"):
                    await handle_callback(db, tuple(data))
                else:
                    await dispatch_message(db, key, identity, user, chat_id, data[2])
            await queue_service.finish(db, TelegramUpdate, key, lease, success=True)
            await db.commit()
    except Exception as exc:
        # Exception text may contain SQL parameters or provider data.
        logger.warning("queue.inbound_failed code=%s", type(exc).__name__)
        async with session_factory() as db:
            await queue_service.finish(db, TelegramUpdate, key, lease, success=False, error_code=type(exc).__name__[:50])
            await db.commit()
    return True


async def deliver_one(session_factory=async_session_factory):
    async with session_factory() as db:
        job = await queue_service.claim(db, DeliveryJob)
        if job is None:
            await db.commit()
            return False
        key, lease, ciphertext = job.id, job.lease_token, job.encrypted_payload
        await db.commit()
    success, error, retry_after = False, None, None
    try:
        payload = queue_service.decrypt(ciphertext)
        method = payload.pop("method")
        if method == "send_message":
            await telegram_client.send_message(**payload)
        elif method == "answer_callback_query":
            await telegram_client.answer_callback_query(**payload)
        else:
            raise ValueError("Unknown delivery method")
        success = True
    except telegram_client.TelegramDeliveryError as exc:
        error, retry_after = exc.code, exc.retry_after
    except Exception:
        error = "delivery_failed"
    async with session_factory() as db:
        await queue_service.finish(db, DeliveryJob, key, lease, success=success, error_code=error, retry_after=retry_after)
        await db.commit()
    return True


async def tick(session_factory=async_session_factory):
    async with session_factory() as db:
        now = datetime.now(timezone.utc)
        await db.execute(insert(WorkerHeartbeat).values(name="telegram", seen_at=now).on_conflict_do_update(index_elements=["name"], set_={"seen_at": now}))
        await queue_service.purge_payloads(db)
        await conversation_service.purge_expired(db)
        await conversation_state_service.purge_expired(db)
        await interaction_service.purge_expired(db)
        await db.commit()
    incoming = await process_one(session_factory)
    outgoing = await deliver_one(session_factory)
    return incoming or outgoing


async def main():
    settings.validate()
    while True:
        try:
            worked = await tick()
        except Exception:
            logger.warning("worker.tick_failed")
            worked = False
        await asyncio.sleep(0.1 if worked else 1)


if __name__ == "__main__":
    asyncio.run(main())
