import itertools

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from api.models.db import (
    AgentAction,
    FitnessGoal,
    TelegramIdentity,
    UserProfile,
)
from tests.test_api.telegram_helpers import confirm_latest_weight

pytestmark = pytest.mark.asyncio

SECRET_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret"}

# These values are shared across the whole test session (the API test database
# is truncated only once), so allocate globally-unique IDs to avoid accidental
# update_id deduplication or identity reuse between tests.
_next_user_id = itertools.count(8000)
_next_update_id = itertools.count(20000)


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


def cb_update(update_id: int, user_id: int, data: str) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb_{update_id}",
            "from": {"id": user_id, "is_bot": False, "first_name": "Alex"},
            "message": {
                "message_id": update_id,
                "chat": {"id": user_id, "type": "private"},
                "date": 1786400000,
            },
            "data": data,
        },
    }


async def _send(async_client: AsyncClient, user_id: int, text: str):
    return await async_client.post(
        "/integrations/telegram/webhook",
        json=msg_update(next(_next_update_id), user_id, text),
        headers=SECRET_HEADERS,
    )


async def _callback(async_client: AsyncClient, user_id: int, data: str):
    return await async_client.post(
        "/integrations/telegram/webhook",
        json=cb_update(next(_next_update_id), user_id, data),
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


async def _pending_action(db_session, user_id) -> AgentAction:
    return await db_session.scalar(
        select(AgentAction).where(
            AgentAction.user_id == user_id,
            AgentAction.status == "pending_confirmation",
        )
    )


async def test_profile_set_confirm_applies_change(async_client, db_session, monkeypatch):
    sent: list[tuple[int, str, dict | None]] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    resp = await _send(async_client, user_id, "/profile set age 30")
    assert resp.status_code == 200
    assert sent[-1][1] == "Update age to 30?"
    assert sent[-1][2] is not None

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    assert action is not None
    assert action.action_type == "update_profile"
    token = action.confirmation_token

    resp = await _callback(async_client, user_id, f"confirm:{token}")
    assert resp.status_code == 200
    assert sent[-1][1] == "Saved — age updated."

    await db_session.refresh(user)
    assert user.age == 30
    await db_session.refresh(action)
    assert action.status == "completed"


async def test_profile_set_cancel_does_not_apply(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/profile set resting_hr 58")

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    token = action.confirmation_token

    resp = await _callback(async_client, user_id, f"cancel:{token}")
    assert resp.status_code == 200
    assert sent[-1] == "Cancelled."

    await db_session.refresh(user)
    assert user.resting_hr is None
    await db_session.refresh(action)
    assert action.status == "cancelled"


async def test_profile_set_invalid_input_clarifies(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/profile set age abc")
    assert sent[-1] == "Age must be a whole number."

    await _send(async_client, user_id, "/profile set age 999")
    assert sent[-1] == "Age must be between 10 and 120."

    await _send(async_client, user_id, "/profile set color blue")
    assert "Unknown field 'color'" in sent[-1]

    user = await _internal_user(db_session, user_id)
    assert user.age is None
    assert user.sex is None


async def test_goal_add_confirm_and_list(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/goals add weight 75 kg by 2026-12-31")
    assert sent[-1] == "New goal: weight 75.0 kg by 2026-12-31. Save it?"

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    assert sent[-1].startswith("Goal created (ref ")

    goal = await db_session.scalar(
        select(FitnessGoal).where(FitnessGoal.user_id == user.id)
    )
    assert goal is not None
    assert goal.goal_type == "weight"
    assert goal.target_value == 75.0
    assert goal.unit == "kg"

    await _send(async_client, user_id, "/goals")
    assert "weight 75.0 kg by 2026-12-31 (active)" in sent[-1]


async def test_goal_frequency_confirm(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/goals add frequency 3 per week")
    assert sent[-1] == "New goal: 3 sessions per week. Save it?"

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    assert sent[-1].startswith("Goal created (ref ")

    goal = await db_session.scalar(
        select(FitnessGoal).where(FitnessGoal.user_id == user.id)
    )
    assert goal.goal_type == "frequency"
    assert goal.target_value == 3.0
    assert goal.unit == "per_week"


async def test_goal_complete_and_remove(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/goals add weight 70 kg")
    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")

    goal = await db_session.scalar(
        select(FitnessGoal).where(FitnessGoal.user_id == user.id)
    )
    ref = str(goal.id)[:8]

    await _send(async_client, user_id, f"/goals complete {ref}")
    assert sent[-1] == f"Goal {ref} marked complete."
    await db_session.refresh(goal)
    assert goal.status == "completed"

    await _send(async_client, user_id, f"/goals remove {ref}")
    assert sent[-1] == f"Remove goal {ref}?"
    remove_action = await _pending_action(db_session, user.id)
    await _callback(
        async_client, user_id, f"confirm:{remove_action.confirmation_token}"
    )
    assert sent[-1] == "Goal removed."

    remaining = await db_session.scalar(
        select(func.count(FitnessGoal.id)).where(FitnessGoal.user_id == user.id)
    )
    assert remaining == 0


async def test_goal_invalid_input_clarifies(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/goals add weight abc")
    assert sent[-1] == "Usage: /goals add weight <value> kg|lb [by YYYY-MM-DD]"

    await _send(async_client, user_id, "/goals add step 1000")
    assert sent[-1] == "Goal type must be 'weight' or 'frequency'."

    await _send(async_client, user_id, "/goals add frequency 0 per week")
    assert sent[-1] == "Frequency must be greater than zero."

    user = await _internal_user(db_session, user_id)
    assert await db_session.scalar(
        select(func.count(FitnessGoal.id)).where(FitnessGoal.user_id == user.id)
    ) == 0


async def test_summaries_report_insufficient_data(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/today")
    assert "Weight: 80.0 kg" in sent[-1]
    assert "Recovery: no health data connected yet" in sent[-1]
    assert "Last workout: none logged yet" in sent[-1]

    await _send(async_client, user_id, "/progress")
    assert "Weight: 80.0 kg" in sent[-1]
    assert "Goals: none active" in sent[-1]

    await _send(async_client, user_id, "/health")
    assert sent[-1].startswith("No health data is connected yet.")


async def test_two_user_goal_isolation(async_client, db_session, monkeypatch):
    sent: list[tuple[int, str]] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text))

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_a = next(_next_user_id)
    user_b = next(_next_user_id)
    await _onboard(async_client, user_a, "80 kg")
    await _onboard(async_client, user_b, "70 kg")

    await _send(async_client, user_a, "/goals add weight 75 kg")
    internal_a = await _internal_user(db_session, user_a)
    action = await _pending_action(db_session, internal_a.id)
    await _callback(async_client, user_a, f"confirm:{action.confirmation_token}")

    await _send(async_client, user_b, "/goals")
    assert "You have no goals yet." in sent[-1][1]

    await _send(async_client, user_a, "/goals")
    assert "weight 75.0 kg (active)" in sent[-1][1]


async def test_confirm_token_is_user_scoped(async_client, db_session, monkeypatch):
    sent: list[tuple[int, str]] = []
    answered: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text))

    async def fake_answer(callback_query_id, text=None):
        answered.append(text or "")

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_a = next(_next_user_id)
    user_b = next(_next_user_id)
    await _onboard(async_client, user_a)
    await _onboard(async_client, user_b)

    await _send(async_client, user_a, "/profile set age 40")
    internal_a = await _internal_user(db_session, user_a)
    action = await _pending_action(db_session, internal_a.id)
    token = action.confirmation_token

    # User B attempts to confirm user A's pending action.
    await _callback(async_client, user_b, f"confirm:{token}")
    assert answered[-1] == "This action is no longer available."

    await db_session.refresh(internal_a)
    assert internal_a.age is None
    await db_session.refresh(action)
    assert action.status == "pending_confirmation"


async def test_duplicate_confirm_does_not_double_write(async_client, db_session, monkeypatch):
    sent: list[str] = []
    answered: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        answered.append(text or "")

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/goals add weight 75 kg")
    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    token = action.confirmation_token

    await _callback(async_client, user_id, f"confirm:{token}")
    await _callback(async_client, user_id, f"confirm:{token}")
    assert answered[-1] == "This action is no longer available."

    count = await db_session.scalar(
        select(func.count(FitnessGoal.id)).where(FitnessGoal.user_id == user.id)
    )
    assert count == 1
