import itertools
import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.models.db import TelegramIdentity, UserProfile
from api.services.dashboard_service import create_link
from tests.test_api.telegram_helpers import confirm_latest_weight

pytestmark = pytest.mark.asyncio

SECRET_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret"}

_next_user_id = itertools.count(18000)
_next_update_id = itertools.count(70000)


def msg_update(update_id: int, user_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": {"id": user_id, "is_bot": False, "first_name": "Alex"},
            "chat": {"id": user_id, "type": "private"},
            "date": 1786400000,
            "text": text,
        },
    }


async def _send(async_client: AsyncClient, user_id: int, text: str):
    return await async_client.post(
        "/integrations/telegram/webhook",
        json=msg_update(next(_next_update_id), user_id, text),
        headers=SECRET_HEADERS,
    )


async def _onboard(async_client: AsyncClient, user_id: int, weight: str = "80 kg") -> None:
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, weight)
    await confirm_latest_weight(async_client, user_id)


async def _internal_user(db_session, telegram_user_id: int) -> UserProfile:
    identity = await db_session.scalar(
        select(TelegramIdentity)
        .where(TelegramIdentity.telegram_user_id == telegram_user_id)
        .options(selectinload(TelegramIdentity.user))
    )
    assert identity is not None
    return identity.user


def _token_from_url(text: str) -> str:
    match = re.search(r"token=([A-Za-z0-9_-]+)", text)
    assert match, f"token not found in: {text}"
    return match.group(1)


async def test_dashboard_link_renders_user_summary(async_client, db_session, monkeypatch):
    sent: list[str] = []
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://fitkit.example.com")

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/dashboard")
    assert "/dashboard?token=" in sent[-1]
    token = _token_from_url(sent[-1])

    resp = await async_client.get("/dashboard", params={"token": token})
    assert resp.status_code == 200
    assert "FitKit" in resp.text
    assert "80.0 kg" in resp.text


async def test_dashboard_invalid_token_returns_401(async_client):
    resp = await async_client.get("/dashboard", params={"token": "not-a-real-token"})
    assert resp.status_code == 401


async def test_dashboard_expired_token_returns_401(async_client, db_session, monkeypatch):
    sent: list[str] = []
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://fitkit.example.com")

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    internal = await _internal_user(db_session, user_id)

    # Create an already-expired link directly through the domain service.
    token, _ = await create_link(db_session, internal.id, ttl_seconds=-1)
    await db_session.commit()

    resp = await async_client.get("/dashboard", params={"token": token})
    assert resp.status_code == 401


async def test_dashboard_links_are_user_scoped(async_client, db_session, monkeypatch):
    sent: list[str] = []
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://fitkit.example.com")

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_a = next(_next_user_id)
    user_b = next(_next_user_id)
    await _onboard(async_client, user_a, "80 kg")
    await _onboard(async_client, user_b, "70 kg")

    await _send(async_client, user_a, "/dashboard")
    token_a = _token_from_url(sent[-1])
    await _send(async_client, user_b, "/dashboard")
    token_b = _token_from_url(sent[-1])

    resp_a = await async_client.get("/dashboard", params={"token": token_a})
    resp_b = await async_client.get("/dashboard", params={"token": token_b})

    assert "80.0 kg" in resp_a.text
    assert "70.0 kg" not in resp_a.text
    assert "70.0 kg" in resp_b.text
    assert "80.0 kg" not in resp_b.text
