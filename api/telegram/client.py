"""Handlers enqueue replies in the current domain transaction; only workers send."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from api.models.db import DeliveryJob
from api.services.queue_service import encrypt


@dataclass
class OutboundContext:
    db: object
    user_id: object
    update_id: int
    sequence: int = 0


_context: ContextVar[OutboundContext | None] = ContextVar("outbound", default=None)


@contextmanager
def outbound_context(db, user_id, update_id):
    value = OutboundContext(db, user_id, update_id)
    token = _context.set(value)
    try:
        yield value
    finally:
        _context.reset(token)


def detach_deleted_user():
    context = _context.get()
    if context is not None:
        context.user_id = None


async def _enqueue(payload: dict):
    context = _context.get()
    if context is None:
        raise RuntimeError("Telegram replies require an outbound transaction context")
    context.sequence += 1
    context.db.add(DeliveryJob(user_id=context.user_id, update_id=context.update_id,
        sequence=context.sequence, encrypted_payload=encrypt(payload)))


async def send_telegram_message(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    from api.telegram.interpretation import take_prepared_opener
    opener = take_prepared_opener()
    if opener:
        text = f"{opener}\n\n{text}"
    # Telegram text messages are limited to 4096 characters. Keep the keyboard
    # on the final chunk so confirmation follows the complete preview.
    for start in range(0, len(text), 4000):
        await _enqueue({"method": "send_message", "chat_id": chat_id, "text": text[start:start + 4000],
                        "reply_markup": reply_markup if start + 4000 >= len(text) else None})


async def answer_callback_query(callback_query_id: str, text: str | None = None) -> None:
    await _enqueue({"method": "answer_callback_query", "callback_query_id": callback_query_id, "text": text})
