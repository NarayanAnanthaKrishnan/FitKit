import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 1.0


def _bot_url(method: str) -> str | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    return f"{_TELEGRAM_API}/bot{token}/{method}"


async def send_message(
    chat_id: int, text: str, reply_markup: dict | None = None
) -> None:
    """Send a text message, optionally with an inline keyboard."""
    url = _bot_url("sendMessage")
    if url is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    payload: dict = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    await _post_with_retry(url, payload)


async def answer_callback_query(
    callback_query_id: str, text: str | None = None
) -> None:
    """Acknowledge a callback query (best effort; failures are not fatal)."""
    url = _bot_url("answerCallbackQuery")
    if url is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    payload: dict = {"callback_query_id": callback_query_id}
    if text is not None:
        payload["text"] = text
    await _post_with_retry(url, payload, raise_on_failure=False)


def build_inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """Build a Telegram inline_keyboard reply_markup structure."""
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": data} for text, data in row]
            for row in rows
        ]
    }


async def _post_with_retry(
    url: str, payload: dict, raise_on_failure: bool = True
) -> None:
    last_status: int | str = "unknown"
    for attempt in range(_MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            last_status = type(exc).__name__
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue
            break

        last_status = response.status_code
        if response.status_code == 429:
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(_retry_after(response))
                continue
            break
        if response.status_code >= 500:
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue
            break

        try:
            body = response.json()
        except ValueError:
            break
        if body.get("ok"):
            return
        break

    # Log without the bot-token URL or any message payload (privacy-by-default).
    logger.warning(
        "Telegram outbound delivery failed (status=%s, attempts=%d)",
        last_status,
        _MAX_ATTEMPTS,
    )
    if raise_on_failure:
        # Never include the bot-token URL in the raised error.
        raise RuntimeError("Telegram delivery failed") from None


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("Retry-After", _BACKOFF_SECONDS))
    except (TypeError, ValueError):
        return _BACKOFF_SECONDS
