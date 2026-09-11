from typing import Any


def extract_message(update: dict[str, Any]) -> tuple[int, int, str, dict[str, Any]] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender = message.get("from")
    chat = message.get("chat")
    text = message.get("text")
    if not isinstance(sender, dict) or not isinstance(chat, dict) or not isinstance(text, str):
        return None
    if chat.get("type") != "private":
        return None
    telegram_user_id = sender.get("id")
    chat_id = chat.get("id")
    if type(telegram_user_id) is not int or type(chat_id) is not int or not 0 < telegram_user_id < 2**63 or chat_id != telegram_user_id or len(text) > 4096:
        return None
    return telegram_user_id, chat_id, text.strip(), {k: str(sender[k])[:255] for k in ("username", "first_name", "last_name") if sender.get(k) is not None}


def extract_callback(
    update: dict[str, Any],
) -> tuple[int, int, str, dict[str, Any], str] | None:
    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return None
    sender = callback.get("from")
    message = callback.get("message")
    data = callback.get("data")
    callback_id = callback.get("id")
    if not isinstance(sender, dict) or not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    telegram_user_id = sender.get("id")
    chat_id = chat.get("id")
    if type(telegram_user_id) is not int or type(chat_id) is not int or not 0 < telegram_user_id < 2**63 or chat_id != telegram_user_id:
        return None
    if not isinstance(data, str) or not isinstance(callback_id, str):
        return None
    if len(data.encode()) > 64 or len(callback_id) > 255:
        return None
    return telegram_user_id, chat_id, data, {k: str(sender[k])[:255] for k in ("username", "first_name", "last_name") if sender.get(k) is not None}, callback_id
