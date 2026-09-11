import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from api.llm.gateway import GatewayResult
from api.llm.schemas import LLMInterpretation
from api.models.db import AgentAction, ConversationState, FeedbackSample, InteractionEvent, TelegramIdentity, UserMemory
from api.services.conversation_service import recent_context, remember_exchange
from tests.test_api.telegram_helpers import SECRET_HEADERS, confirm_latest_weight, enable_ai, post_callback

pytestmark = pytest.mark.asyncio
_users = itertools.count(71000)
_updates = itertools.count(171000)


def message(user_id, text):
    update_id = next(_updates)
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


async def send(client, user_id, text):
    return await client.post("/integrations/telegram/webhook", json=message(user_id, text), headers=SECRET_HEADERS)


async def onboard(client, user_id):
    await send(client, user_id, "/start")
    await send(client, user_id, "80 kg")
    await confirm_latest_weight(client, user_id)
    await send(client, user_id, "skip")
    await send(client, user_id, "skip")


async def identity_for(db, external_id):
    return await db.scalar(select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == external_id))


async def test_complete_workout_can_be_logged_without_slash(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)

    await send(async_client, user_id, "I did bench, 3 sets of 8 at 80 kg")

    identity = await identity_for(db_session, user_id)
    action = await db_session.scalar(select(AgentAction).where(
        AgentAction.user_id == identity.user_id, AgentAction.status == "pending_confirmation"
    ))
    assert action.action_type == "log_workout"
    assert len(action.input_payload["sets"]) == 3
    assert any("Save this workout?" in text for text, _ in sent)


async def test_short_session_focus_continues_into_grounded_planning(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    monkeypatch.setenv("LLM_ENABLED", "0")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)

    await send(async_client, user_id, "It's leg day today")
    identity = await identity_for(db_session, user_id)
    state = await db_session.get(ConversationState, identity.user_id)
    assert state.kind == "session_focus"
    assert "planning the session or logging" in sent[-1][0]

    await send(async_client, user_id, "Planning")
    await db_session.refresh(state)
    assert state.kind == "routine_planning"
    assert "don’t have a completed workout" in sent[-1][0]

    await send(async_client, user_id, "What do you remember about me?")
    assert "Current conversation focus: legs" in sent[-1][0]
    assert "no workouts recorded yet" in sent[-1][0]


async def test_recent_transcript_becomes_one_grounded_routine_review_task(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    monkeypatch.setenv("LLM_ENABLED", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)
    await enable_ai(async_client, user_id)

    review = GatewayResult(interpretation=LLMInterpretation.model_validate({
        "intent": "routine_review",
        "confidence": 0.97,
        "payload": {
            "exercise_queries": ["lat pulldown", "seated cable row", "hammer curl"],
            "equipment": None,
        },
    }), latency_ms=1050)
    interpret = AsyncMock(return_value=review)
    polish = AsyncMock()
    with patch("api.llm.gateway.interpret_free_text", interpret), patch("api.llm.gateway.polish_reply", polish):
        await send(async_client, user_id, "Okay if not soccer I'm hitting back biceps")
        await send(async_client, user_id, "Help me plan it")
        await send(async_client, user_id, "I have a gym so tell me the most effective ones")
        await send(async_client, user_id, "lat pulldown, seated cable row, hammer curl")
        await send(async_client, user_id, "Sure thanks")

    assert interpret.await_count == 1
    assert polish.await_count == 0
    texts = [text for text, _ in sent]
    assert any("improves an existing routine rather than inventing one" in text for text in texts)
    assert any("I checked the exercises you listed" in text for text in texts)
    assert any("Nothing was saved or changed" in text for text in texts)
    assert not any("pull-ups or assisted pull-ups" in text.casefold() for text in texts)

    identity = await identity_for(db_session, user_id)
    internal_user_id = identity.user_id
    db_session.expire_all()
    state = await db_session.get(ConversationState, internal_user_id)
    from api.services.queue_service import decrypt
    state_payload = decrypt(state.encrypted_payload)
    assert state.kind == "routine_planning"
    assert state_payload["focus"] == "back and biceps"
    assert state_payload["equipment"] == "gym"
    assert state_payload["stage"] == "paused"
    task_events = (await db_session.scalars(select(InteractionEvent).where(
        InteractionEvent.user_id == internal_user_id,
        InteractionEvent.task_id.is_not(None),
    ))).all()
    assert {event.outcome for event in task_events} >= {"started", "advanced", "completed", "paused"}
    assert all(event.task_stage for event in task_events)


async def test_recent_context_orders_equal_timestamp_pair_user_first(db_session):
    identity = await db_session.scalar(select(TelegramIdentity).limit(1))
    await remember_exchange(db_session, identity.user_id, "user message", "assistant reply")
    turns = await recent_context(db_session, identity.user_id)
    assert turns == [
        {"role": "user", "content": "user message"},
        {"role": "assistant", "content": "assistant reply"},
    ]


async def test_expired_routine_task_emits_content_free_lifecycle_event(db_session):
    from api.services import conversation_state_service

    identity = await db_session.scalar(select(TelegramIdentity).limit(1))
    task_id = uuid.uuid4()
    await conversation_state_service.set_state(db_session, identity.user_id, "routine_planning", {
        "task_id": str(task_id),
        "focus": "pull",
        "stage": "awaiting_current_exercises",
    })
    state = await db_session.get(ConversationState, identity.user_id)
    state.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await conversation_state_service.purge_expired(db_session)

    event = await db_session.scalar(select(InteractionEvent).where(
        InteractionEvent.task_id == task_id,
        InteractionEvent.outcome == "expired",
    ))
    assert event is not None
    assert event.reason_code == "task_timeout"
    assert event.task_stage == "awaiting_current_exercises"


async def test_missing_workout_load_is_collected_on_next_turn(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)

    await send(async_client, user_id, "bench 3x8")
    identity = await identity_for(db_session, user_id)
    assert (await db_session.get(ConversationState, identity.user_id)).kind == "workout_missing_load"
    await send(async_client, user_id, "80 kg")

    action = await db_session.scalar(select(AgentAction).where(
        AgentAction.user_id == identity.user_id, AgentAction.status == "pending_confirmation"
    ))
    assert action.action_type == "log_workout"
    assert await db_session.get(ConversationState, identity.user_id) is None


async def test_read_only_question_preserves_pending_preview(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)
    await send(async_client, user_id, "I did squat 3x5 at 100 kg")
    identity = await identity_for(db_session, user_id)
    action = await db_session.scalar(select(AgentAction).where(
        AgentAction.user_id == identity.user_id, AgentAction.status == "pending_confirmation"
    ))

    await send(async_client, user_id, "How am I doing?")

    await db_session.refresh(action)
    assert action.status == "pending_confirmation"
    assert any("earlier preview is still waiting" in text for text, _ in sent)
    event = await db_session.scalar(select(InteractionEvent).where(InteractionEvent.intent == "progress"))
    assert event.reason_code == "preview_preserved"


async def test_natural_correction_updates_and_rotates_workout_preview(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)
    await send(async_client, user_id, "I did push ups 3x8 at 20 kg")
    identity = await identity_for(db_session, user_id)
    action = await db_session.scalar(select(AgentAction).where(
        AgentAction.user_id == identity.user_id, AgentAction.status == "pending_confirmation"
    ))
    first_token = action.confirmation_token

    await send(async_client, user_id, "actually bodyweight")

    await db_session.refresh(action)
    assert all(item["weight_kg"] == 0 for item in action.input_payload["sets"])
    assert action.confirmation_token != first_token


async def test_natural_delete_only_starts_exact_confirmation(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)

    await send(async_client, user_id, "delete my account")

    identity = await identity_for(db_session, user_id)
    action = await db_session.scalar(select(AgentAction).where(
        AgentAction.user_id == identity.user_id, AgentAction.status == "pending_confirmation"
    ))
    assert action.action_type == "delete_user"
    assert any("DELETE" in text and "confirm" in text for text, _ in sent)


async def test_negative_rating_requires_disclosed_share_before_feedback_is_retained(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    monkeypatch.setattr("api.services.telegram_client.answer_callback_query", lambda callback_id, text=None: _answer())
    user_id = next(_users)
    await onboard(async_client, user_id)
    await send(async_client, user_id, "please perform an unsupported mystery action")
    identity = await identity_for(db_session, user_id)
    event = await db_session.scalar(select(InteractionEvent).where(
        InteractionEvent.user_id == identity.user_id,
        InteractionEvent.reason_code == "unsupported_or_provider_unavailable",
    ))

    await post_callback(async_client, user_id, f"rate:down:{event.id}")
    await send(async_client, user_id, "The reply did not explain what information was missing.")
    assert await db_session.scalar(select(FeedbackSample).where(FeedbackSample.user_id == identity.user_id)) is None

    await post_callback(async_client, user_id, "feedback:share")
    sample = await db_session.scalar(select(FeedbackSample).where(FeedbackSample.user_id == identity.user_id))
    assert sample is not None
    assert "did not explain" not in sample.encrypted_content
    assert datetime.now(timezone.utc) + timedelta(days=29) < sample.expires_at
    assert await db_session.get(ConversationState, identity.user_id) is None


async def test_long_term_preference_memory_requires_confirmation_and_can_be_cleared(async_client, db_session, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "1")
    sent = []
    monkeypatch.setattr("api.services.telegram_client.send_message", lambda chat_id, text, reply_markup=None: _append(sent, text, reply_markup))
    user_id = next(_users)
    await onboard(async_client, user_id)
    identity = await identity_for(db_session, user_id)

    await send(async_client, user_id, "Remember that I train at home with dumbbells")
    action = await db_session.scalar(select(AgentAction).where(
        AgentAction.user_id == identity.user_id,
        AgentAction.action_type == "remember_preference",
        AgentAction.status == "pending_confirmation",
    ))
    assert "dumbbells" not in str(action.input_payload).lower()
    assert await db_session.scalar(select(UserMemory).where(UserMemory.user_id == identity.user_id)) is None

    await post_callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    memory = await db_session.scalar(select(UserMemory).where(UserMemory.user_id == identity.user_id))
    assert memory is not None and "dumbbells" not in memory.encrypted_content.lower()
    await send(async_client, user_id, "What do you remember about me?")
    assert "I train at home with dumbbells" in sent[-1][0]

    await send(async_client, user_id, "Forget my saved preferences")
    clear_action = await db_session.scalar(select(AgentAction).where(
        AgentAction.user_id == identity.user_id,
        AgentAction.action_type == "clear_memories",
        AgentAction.status == "pending_confirmation",
    ))
    await post_callback(async_client, user_id, f"confirm:{clear_action.confirmation_token}")
    assert await db_session.scalar(select(UserMemory).where(UserMemory.user_id == identity.user_id)) is None


async def _append(target, text, reply_markup):
    target.append((text, reply_markup))


async def _answer():
    return None
