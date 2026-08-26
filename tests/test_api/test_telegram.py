import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from api.models.db import (
    AgentAction,
    TelegramIdentity,
    TelegramUpdate,
    WeightMeasurement,
)
from tests.test_api.telegram_helpers import (
    SECRET_HEADERS,
    post_callback,
    cancel_latest_weight,
    confirm_latest_weight,
)

pytestmark = pytest.mark.asyncio


def start_update(update_id: int, user_id: int = 4242, text: str = "/start") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Alex",
                "username": "alex_fit",
            },
            "chat": {"id": user_id, "type": "private"},
            "date": 1786400000,
            "text": text,
        },
    }


async def test_webhook_rejects_missing_secret(async_client: AsyncClient):
    response = await async_client.post(
        "/integrations/telegram/webhook", json=start_update(1)
    )
    assert response.status_code == 401


async def test_webhook_rejects_wrong_secret(async_client: AsyncClient):
    response = await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(1),
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret-x"},
    )
    assert response.status_code == 401


async def test_start_creates_identity_and_sends_onboarding_prompt(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[tuple[int, str]] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    response = await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(100),
        headers=SECRET_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    identity = await db_session.scalar(
        select(TelegramIdentity)
        .where(TelegramIdentity.telegram_user_id == 4242)
        .options(selectinload(TelegramIdentity.user))
    )
    assert identity is not None
    assert identity.onboarding_step == "awaiting_weight"
    assert identity.user.weight_kg is None
    assert await db_session.scalar(
        select(func.count(WeightMeasurement.id)).where(
            WeightMeasurement.user_id == identity.user_id
        )
    ) == 0
    assert sent == [
        (
            4242,
            "Welcome to FitKit! I can help you track workouts, weight, activity, "
            "and progress. What is your current weight? Reply with a value such as 80 kg.",
        )
    ]


async def test_weight_message_previews_then_confirms_onboarding(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[tuple[int, str, dict | None]] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append((chat_id, text, reply_markup))

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(200, user_id=5252),
        headers=SECRET_HEADERS,
    )
    response = await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(201, user_id=5252, text="176 lb"),
        headers=SECRET_HEADERS,
    )

    assert response.status_code == 200
    # Nothing is written before confirmation.
    identity = await db_session.scalar(
        select(TelegramIdentity)
        .where(TelegramIdentity.telegram_user_id == 5252)
        .options(selectinload(TelegramIdentity.user))
    )
    assert identity is not None
    assert identity.onboarding_step == "awaiting_weight"
    assert identity.user.weight_kg is None
    assert (
        await db_session.scalar(
            select(func.count(WeightMeasurement.id)).where(
                WeightMeasurement.user_id == identity.user_id
            )
        )
        == 0
    )
    # The bot asks for reviewable confirmation with a Save button.
    assert sent[-1][1] == "Record your current weight as 79.83 kg?"
    assert sent[-1][2] is not None

    confirm = await confirm_latest_weight(async_client, 5252)
    assert confirm.status_code == 200

    await db_session.refresh(identity)
    await db_session.refresh(identity.user)
    assert identity.onboarding_step == "complete"
    assert identity.user.weight_kg == pytest.approx(79.83, abs=0.01)
    measurement = await db_session.scalar(
        select(WeightMeasurement).where(
            WeightMeasurement.user_id == identity.user_id
        )
    )
    assert measurement is not None
    assert measurement.weight_kg == pytest.approx(79.83, abs=0.01)
    assert sent[-1][:2] == (
        5252,
        "Saved — your current weight is 79.83 kg. "
        "Your profile is ready. Send /help to continue.",
    )


async def test_weight_confirm_is_single_write_on_duplicate_clicks(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(210, user_id=5353),
        headers=SECRET_HEADERS,
    )
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(211, user_id=5353, text="80 kg"),
        headers=SECRET_HEADERS,
    )

    first = await confirm_latest_weight(async_client, 5353)
    second = await post_callback(async_client, 5353, "confirm:not-a-token")

    assert first.status_code == 200
    assert second.status_code == 200
    identity = await db_session.scalar(
        select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == 5353)
    )
    assert await db_session.scalar(
        select(func.count(WeightMeasurement.id)).where(
            WeightMeasurement.user_id == identity.user_id
        )
    ) == 1


async def test_weight_cancel_does_not_save(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(220, user_id=5454),
        headers=SECRET_HEADERS,
    )
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(221, user_id=5454, text="82 kg"),
        headers=SECRET_HEADERS,
    )
    cancelled = await cancel_latest_weight(async_client, 5454)

    assert cancelled.status_code == 200
    assert sent[-1] == "Cancelled."
    identity = await db_session.scalar(
        select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == 5454)
    )
    assert identity.onboarding_step == "awaiting_weight"
    assert (
        await db_session.scalar(
            select(func.count(WeightMeasurement.id)).where(
                WeightMeasurement.user_id == identity.user_id
            )
        )
        == 0
    )


async def test_expired_weight_confirmation_cannot_be_saved(
    async_client: AsyncClient, db_session, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(230, user_id=5555),
        headers=SECRET_HEADERS,
    )
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(231, user_id=5555, text="84 kg"),
        headers=SECRET_HEADERS,
    )
    identity = await db_session.scalar(
        select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == 5555)
    )
    action = await db_session.scalar(
        select(AgentAction).where(
            AgentAction.user_id == identity.user_id,
            AgentAction.action_type == "record_weight",
            AgentAction.status == "pending_confirmation",
        )
    )
    action.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    response = await confirm_latest_weight(async_client, 5555)

    assert response.status_code == 200
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_weight"
    assert (
        await db_session.scalar(
            select(func.count(WeightMeasurement.id)).where(
                WeightMeasurement.user_id == identity.user_id
            )
        )
        == 0
    )


async def test_delete_requires_confirmation_and_cancel_preserves_data(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(250, user_id=5757),
        headers=SECRET_HEADERS,
    )
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(251, user_id=5757, text="80 kg"),
        headers=SECRET_HEADERS,
    )
    await confirm_latest_weight(async_client, 5757)

    pending = await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(252, user_id=5757, text="/delete"),
        headers=SECRET_HEADERS,
    )
    assert pending.status_code == 200
    assert "Reply DELETE to confirm" in sent[-1]

    cancelled = await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(253, user_id=5757, text="/cancel"),
        headers=SECRET_HEADERS,
    )
    assert cancelled.status_code == 200
    assert sent[-1] == "Deletion cancelled. Your data is safe."
    identity = await db_session.scalar(
        select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == 5757)
    )
    assert identity is not None
    assert identity.onboarding_step == "complete"
    assert await db_session.scalar(
        select(func.count(WeightMeasurement.id)).where(
            WeightMeasurement.user_id == identity.user_id
        )
    ) == 1


async def test_delete_confirm_removes_only_that_users_data(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(260, user_id=5858),
        headers=SECRET_HEADERS,
    )
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(261, user_id=5858, text="80 kg"),
        headers=SECRET_HEADERS,
    )
    await confirm_latest_weight(async_client, 5858)
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(262, user_id=5959),
        headers=SECRET_HEADERS,
    )
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(263, user_id=5959, text="70 kg"),
        headers=SECRET_HEADERS,
    )
    await confirm_latest_weight(async_client, 5959)
    await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(264, user_id=5858, text="/delete"),
        headers=SECRET_HEADERS,
    )

    response = await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(265, user_id=5858, text="DELETE"),
        headers=SECRET_HEADERS,
    )

    assert response.status_code == 200
    assert sent[-1] == (
        "Your FitKit data has been permanently deleted. "
        "Send /start if you want to begin again."
    )
    assert await db_session.scalar(
        select(func.count(TelegramIdentity.id)).where(
            TelegramIdentity.telegram_user_id == 5858
        )
    ) == 0
    # The deleted Telegram identity must be gone, while the other Telegram
    # account remains intact. Do not assert a global profile count because
    # legacy API tests may create non-Telegram profiles.
    remaining_identity = await db_session.scalar(
        select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == 5959)
    )
    assert remaining_identity is not None
    assert await db_session.scalar(
        select(func.count(WeightMeasurement.id)).where(
            WeightMeasurement.user_id == remaining_identity.user_id
        )
    ) == 1
    current_update = await db_session.get(TelegramUpdate, 265)
    assert current_update is not None
    assert current_update.telegram_user_id is None
    assert current_update.status == "processed"

    retry = await async_client.post(
        "/integrations/telegram/webhook",
        json=start_update(265, user_id=5858, text="DELETE"),
        headers=SECRET_HEADERS,
    )
    assert retry.status_code == 200
    assert retry.json() == {"ok": True, "duplicate": True}


async def test_group_messages_are_ignored_without_creating_an_identity(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    update = start_update(270, user_id=6060)
    update["message"]["chat"] = {"id": -6060, "type": "group"}

    response = await async_client.post(
        "/integrations/telegram/webhook", json=update, headers=SECRET_HEADERS
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": True}
    assert sent == []
    assert await db_session.scalar(
        select(func.count(TelegramIdentity.id)).where(
            TelegramIdentity.telegram_user_id == 6060
        )
    ) == 0


async def test_duplicate_update_is_ignored(
    async_client: AsyncClient, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, reply_markup=None) -> None:
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    update = start_update(300, user_id=6262)

    first = await async_client.post(
        "/integrations/telegram/webhook", json=update, headers=SECRET_HEADERS
    )
    second = await async_client.post(
        "/integrations/telegram/webhook", json=update, headers=SECRET_HEADERS
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"ok": True, "duplicate": True}
    assert len(sent) == 1
    assert await db_session.scalar(
        select(func.count(TelegramUpdate.update_id)).where(
            TelegramUpdate.update_id == 300
        )
    ) == 1
    assert await db_session.scalar(
        select(func.count(TelegramIdentity.id)).where(
            TelegramIdentity.telegram_user_id == 6262
        )
    ) == 1
