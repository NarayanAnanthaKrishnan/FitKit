import itertools
import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.models.db import HealthMetric, HealthPairing, TelegramIdentity, UserProfile
from tests.test_api.telegram_helpers import confirm_latest_weight

pytestmark = pytest.mark.asyncio

SECRET_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret"}

_next_user_id = itertools.count(16000)
_next_update_id = itertools.count(60000)

VALID_PAYLOAD = {
    "data": {
        "metrics": [
            {
                "name": "heart_rate_variability",
                "units": "ms",
                "data": [{"qty": 58.2, "date": "2026-07-25 07:00:00 +0000"}],
            },
            {
                "name": "sleep_analysis",
                "units": "hr",
                "data": [
                    {
                        "date": "2026-07-25",
                        "totalSleep": 7.2,
                        "asleep": 6.8,
                        "sleepStart": "2026-07-24 23:10:00 +0000",
                        "sleepEnd": "2026-07-25 06:45:00 +0000",
                        "inBed": 7.5,
                    }
                ],
            },
        ]
    }
}


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


async def _onboard(async_client: AsyncClient, user_id: int) -> None:
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, "80 kg")
    await confirm_latest_weight(async_client, user_id)


async def _internal_user(db_session, telegram_user_id: int) -> UserProfile:
    identity = await db_session.scalar(
        select(TelegramIdentity)
        .where(TelegramIdentity.telegram_user_id == telegram_user_id)
        .options(selectinload(TelegramIdentity.user))
    )
    assert identity is not None
    return identity.user


def _token_from(text: str) -> str:
    match = re.search(r"X-Health-Pairing-Token: (\S+)", text)
    assert match, f"pairing token not found in: {text}"
    return match.group(1)


async def _metric_rows(db_session, user_id):
    return list(
        (
            await db_session.execute(
                select(HealthMetric).where(HealthMetric.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )


async def test_connect_health_and_ingest_with_token(
    async_client, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/connect-health")
    assert "X-Health-Pairing-Token:" in sent[-1]
    token = _token_from(sent[-1])

    internal = await _internal_user(db_session, user_id)
    pairing = await db_session.scalar(
        select(HealthPairing).where(HealthPairing.user_id == internal.id)
    )
    assert pairing is not None
    assert pairing.status == "active"
    # The raw token is never stored.
    assert pairing.token_hash != token

    resp = await async_client.post(
        "/ingest/health",
        json=VALID_PAYLOAD,
        headers={"X-Health-Pairing-Token": token},
    )
    assert resp.status_code == 201
    assert resp.json()["inserted"] == 2

    rows = await _metric_rows(db_session, internal.id)
    assert len(rows) == 2
    assert {r.metric_type for r in rows} == {"hrv", "sleep_hours"}


async def test_invalid_pairing_token_returns_401(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/connect-health")

    resp = await async_client.post(
        "/ingest/health",
        json=VALID_PAYLOAD,
        headers={"X-Health-Pairing-Token": "definitely-not-a-real-token"},
    )
    assert resp.status_code == 401


async def test_rotating_token_revokes_previous(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/connect-health")
    first_token = _token_from(sent[-1])

    await _send(async_client, user_id, "/connect-health")
    second_token = _token_from(sent[-1])
    assert second_token != first_token

    internal = await _internal_user(db_session, user_id)
    pairings = list(
        (
            await db_session.execute(
                select(HealthPairing).where(HealthPairing.user_id == internal.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(pairings) == 2
    assert {p.status for p in pairings} == {"active", "revoked"}

    # The old token is now rejected.
    resp = await async_client.post(
        "/ingest/health",
        json=VALID_PAYLOAD,
        headers={"X-Health-Pairing-Token": first_token},
    )
    assert resp.status_code == 401


async def test_pairing_token_is_user_scoped(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_a = next(_next_user_id)
    user_b = next(_next_user_id)
    await _onboard(async_client, user_a)
    await _onboard(async_client, user_b)

    await _send(async_client, user_a, "/connect-health")
    token_a = _token_from(sent[-1])
    await _send(async_client, user_b, "/connect-health")
    token_b = _token_from(sent[-1])

    internal_a = await _internal_user(db_session, user_a)
    internal_b = await _internal_user(db_session, user_b)

    await async_client.post(
        "/ingest/health",
        json=VALID_PAYLOAD,
        headers={"X-Health-Pairing-Token": token_a},
    )

    assert len(await _metric_rows(db_session, internal_a.id)) == 2
    assert len(await _metric_rows(db_session, internal_b.id)) == 0


async def _connect_and_token(async_client, db_session, monkeypatch, user_id):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/connect-health")
    return _token_from(sent[-1])


async def test_shortcut_ingest_flat_payload(async_client, db_session, monkeypatch):
    user_id = next(_next_user_id)
    token = await _connect_and_token(async_client, db_session, monkeypatch, user_id)
    internal = await _internal_user(db_session, user_id)

    resp = await async_client.post(
        "/ingest/shortcut",
        json={"hrv": 58.2, "resting_hr": 54, "sleep_hours": 6.8},
        headers={"X-Health-Pairing-Token": token},
    )
    assert resp.status_code == 201
    assert resp.json()["inserted"] == 3

    rows = await _metric_rows(db_session, internal.id)
    assert {r.metric_type for r in rows} == {"hrv", "resting_hr", "sleep_hours"}
    assert all(r.source == "apple_shortcuts" for r in rows)


async def test_shortcut_ingest_idempotent_with_timestamp(
    async_client, db_session, monkeypatch
):
    user_id = next(_next_user_id)
    token = await _connect_and_token(async_client, db_session, monkeypatch, user_id)
    internal = await _internal_user(db_session, user_id)

    payload = {"measured_at": "2026-07-25T07:00:00Z", "hrv": 58.2}
    first = await async_client.post(
        "/ingest/shortcut",
        json=payload,
        headers={"X-Health-Pairing-Token": token},
    )
    second = await async_client.post(
        "/ingest/shortcut",
        json=payload,
        headers={"X-Health-Pairing-Token": token},
    )
    assert first.json()["inserted"] == 1
    assert second.json()["inserted"] == 0
    assert len(await _metric_rows(db_session, internal.id)) == 1


async def test_shortcut_ingest_rejects_invalid_token(async_client):
    resp = await async_client.post(
        "/ingest/shortcut",
        json={"hrv": 58.2},
        headers={"X-Health-Pairing-Token": "not-a-real-token"},
    )
    assert resp.status_code == 401


async def test_shortcut_ingest_rejects_out_of_range_values(
    async_client, db_session, monkeypatch
):
    user_id = next(_next_user_id)
    token = await _connect_and_token(async_client, db_session, monkeypatch, user_id)
    internal = await _internal_user(db_session, user_id)

    resp = await async_client.post(
        "/ingest/shortcut",
        json={"sleep_hours": 30},
        headers={"X-Health-Pairing-Token": token},
    )
    assert resp.status_code == 422
    assert len(await _metric_rows(db_session, internal.id)) == 0


async def test_pairing_works_while_legacy_auth_disabled(
    async_client, db_session, monkeypatch
):
    monkeypatch.setenv("ALLOW_LEGACY_INGEST_AUTH", "0")
    user_id = next(_next_user_id)
    token = await _connect_and_token(async_client, db_session, monkeypatch, user_id)
    internal = await _internal_user(db_session, user_id)

    resp = await async_client.post(
        "/ingest/health",
        json=VALID_PAYLOAD,
        headers={"X-Health-Pairing-Token": token},
    )
    assert resp.status_code == 201
    assert len(await _metric_rows(db_session, internal.id)) == 2
