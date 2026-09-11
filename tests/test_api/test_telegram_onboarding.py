from api.llm.schemas import LLMInterpretation
from api.llm.gateway import GatewayResult
from tests.test_api.telegram_helpers import enable_ai
import itertools
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from unittest.mock import AsyncMock, patch

from api.models.db import AgentAction, FitnessGoal, TelegramIdentity, UserProfile
from tests.test_api.telegram_helpers import confirm_latest_weight

pytestmark = pytest.mark.asyncio

SECRET_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret"}

_next_user_id = itertools.count(40000)
_next_update_id = itertools.count(95000)


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


async def _pending_action(db_session, user_id):
    return await db_session.scalar(
        select(AgentAction).where(
            AgentAction.user_id == user_id,
            AgentAction.status == "pending_confirmation",
        )
    )


async def test_onboarding_weight_then_goal_then_profile_flow(async_client, db_session, monkeypatch):
    """Full 3-step onboarding: weight -> goal (deterministic) -> profile skip -> complete."""
    monkeypatch.setenv("LLM_ENABLED", "0")
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.services.telegram_client.send_message", fake_send)
    monkeypatch.setattr("api.services.telegram_client.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _send(async_client, user_id, "/start")
    assert "Weight is optional" in sent[-1]
    identity = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_id))
    assert identity.onboarding_step == "awaiting_weight"

    await _send(async_client, user_id, "80 kg")
    assert "Record your current weight as 80.00 kg?" in sent[-1]
    # confirm weight
    await confirm_latest_weight(async_client, user_id)
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_goal"
    assert "What would you like to accomplish?" in sent[-1]

    # Send goal deterministically
    await _send(async_client, user_id, "weight 75 kg by 2026-12-31")
    assert "New goal: weight 75.0 kg by 2026-12-31. Save it?" in sent[-1]
    user = await db_session.scalar(select(UserProfile).where(UserProfile.id == identity.user_id))
    action = await _pending_action(db_session, user.id)
    assert action is not None and action.action_type == "create_goal"
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_profile_optin"
    assert "Age and sex are optional" in sent[-1]

    # Skip profile -> complete
    await _send(async_client, user_id, "/skip")
    await db_session.refresh(identity)
    assert identity.onboarding_step == "complete"
    assert "All set" in sent[-1]


async def test_onboarding_llm_goal_creates_preview(async_client, db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.services.telegram_client.send_message", fake_send)
    monkeypatch.setattr("api.services.telegram_client.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, "78 kg")
    await confirm_latest_weight(async_client, user_id)
    # now awaiting_goal
    identity = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_id))
    assert identity.onboarding_step == "awaiting_goal"

    mock_interp = AsyncMock(return_value=GatewayResult(interpretation=LLMInterpretation.model_validate({
            "intent": "create_goal", "confidence": 0.92,
            "payload": {"goal_type": "frequency", "target_value": 3, "unit": "per_week", "target_date": None},
            "clarification": None
        })))

    await enable_ai(async_client, user_id)
    with patch("api.llm.gateway.interpret_free_text", mock_interp):
        await _send(async_client, user_id, "I want to train 3 times per week")

    assert any("3 sessions per week" in t for t in sent)
    user = await db_session.scalar(select(UserProfile).where(UserProfile.id == identity.user_id))
    action = await _pending_action(db_session, user.id)
    assert action is not None
    assert action.action_type == "create_goal"
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_profile_optin"

    # Verify goal persisted
    goal = await db_session.scalar(select(FitnessGoal).where(FitnessGoal.user_id == user.id))
    assert goal is not None
    assert goal.goal_type == "frequency"


async def test_onboarding_llm_vague_goal_asks_clarification(async_client, db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.services.telegram_client.send_message", fake_send)

    user_id = next(_next_user_id)
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, "80 kg")
    await confirm_latest_weight(async_client, user_id)

    # Mock vague intent -> unknown with clarification
    mock_interp = AsyncMock(return_value=GatewayResult(interpretation=LLMInterpretation.model_validate({
            "intent": "unknown", "confidence": 0.9,
            "payload": None, "clarification": "Do you mean losing weight or training frequency? e.g. 'weight 75 kg' or '3 times per week'"
        })))
    await enable_ai(async_client, user_id)
    with patch("api.llm.gateway.interpret_free_text", mock_interp):
        await _send(async_client, user_id, "I want to get healthier")

    assert any("Do you mean" in t for t in sent)
    identity = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_id))
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_goal"
    # no goal created
    user = await db_session.scalar(select(UserProfile).where(UserProfile.id == identity.user_id))
    count = await db_session.scalar(select(func.count(FitnessGoal.id)).where(FitnessGoal.user_id == user.id))
    assert count == 0


async def test_onboarding_skip_goal_then_profile(async_client, db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "0")
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.services.telegram_client.send_message", fake_send)

    user_id = next(_next_user_id)
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, "80 kg")
    await confirm_latest_weight(async_client, user_id)

    await _send(async_client, user_id, "/skip")
    identity = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_id))
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_profile_optin"

    await _send(async_client, user_id, "/skip")
    await db_session.refresh(identity)
    assert identity.onboarding_step == "complete"


async def test_onboarding_goal_via_text_skip_keyword(async_client, db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "0")
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.services.telegram_client.send_message", fake_send)

    user_id = next(_next_user_id)
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, "70 kg")
    await confirm_latest_weight(async_client, user_id)

    await _send(async_client, user_id, "skip")
    identity = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_id))
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_profile_optin"


async def test_onboard_command_restarts_flow(async_client, db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "0")
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.services.telegram_client.send_message", fake_send)
    monkeypatch.setattr("api.services.telegram_client.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    # Complete full onboarding
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, "80 kg")
    await confirm_latest_weight(async_client, user_id)
    await _send(async_client, user_id, "weight 75 kg")
    identity = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_id))
    user = await db_session.scalar(select(UserProfile).where(UserProfile.id == identity.user_id))
    action = await _pending_action(db_session, user.id)
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    await _send(async_client, user_id, "/skip")
    await db_session.refresh(identity)
    assert identity.onboarding_step == "complete"

    # Restart
    await _send(async_client, user_id, "/onboard")
    await db_session.refresh(identity)
    assert identity.onboarding_step == "awaiting_goal"
    assert "What would you like to accomplish?" in sent[-1]


async def test_onboarding_is_user_scoped(async_client, db_session, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "0")
    sent: list[tuple[int, str]] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text))

    monkeypatch.setattr("api.services.telegram_client.send_message", fake_send)

    user_a = next(_next_user_id)
    user_b = next(_next_user_id)
    for uid in (user_a, user_b):
        await _send(async_client, uid, "/start")
        await _send(async_client, uid, "80 kg")
        await confirm_latest_weight(async_client, uid)

    # User A sets goal, B skips
    await _send(async_client, user_a, "weight 75 kg")
    await _send(async_client, user_b, "/skip")
    # B also skips profile to complete
    await _send(async_client, user_b, "/skip")

    identity_a = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_a))
    identity_b = await db_session.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == user_b))
    await db_session.refresh(identity_a)
    await db_session.refresh(identity_b)
    assert identity_a.onboarding_step == "awaiting_goal"  # pending confirm, not yet completed
    assert identity_b.onboarding_step == "complete"
