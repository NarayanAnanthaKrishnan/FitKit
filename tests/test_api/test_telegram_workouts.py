import itertools
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from api.models.db import (
    AgentAction,
    TelegramIdentity,
    UserProfile,
    WorkoutSession,
)

pytestmark = pytest.mark.asyncio

SECRET_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret"}

# Distinct ranges from test_telegram_mvp to avoid update_id/telegram_id collision.
_next_user_id = itertools.count(9000)
_next_update_id = itertools.count(30000)


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


async def _onboard(async_client: AsyncClient, user_id: int) -> None:
    await _send(async_client, user_id, "/start")
    await _send(async_client, user_id, "80 kg")


async def _internal_user(db_session, telegram_user_id: int) -> UserProfile:
    identity = await db_session.scalar(
        select(TelegramIdentity).where(
            TelegramIdentity.telegram_user_id == telegram_user_id
        )
    )
    assert identity is not None
    return await db_session.get(UserProfile, identity.user_id)


async def _pending_action(db_session, user_id) -> AgentAction:
    return await db_session.scalar(
        select(AgentAction).where(
            AgentAction.user_id == user_id,
            AgentAction.status == "pending_confirmation",
        )
    )


async def _workout_count(db_session, user_id) -> int:
    return await db_session.scalar(
        select(func.count(WorkoutSession.id)).where(
            WorkoutSession.user_id == user_id
        )
    )


async def test_log_preview_and_confirm_saves_workout(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/log bench press 3x8 at 80 kg, rpe 8")
    assert "I understood:" in sent[-1]
    assert "barbell bench press" in sent[-1].lower() or "bench press" in sent[-1].lower()
    assert "Save this workout?" in sent[-1]

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    assert action is not None
    assert action.action_type == "log_workout"

    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    assert sent[-1].startswith("Workout saved (3 set(s)).")

    assert await _workout_count(db_session, user.id) == 1

    await db_session.refresh(action)
    assert action.status == "completed"
    assert action.result_payload["workout_id"]


async def test_log_cancel_does_not_save(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/log squat 100 kg for 5, 5, 4")
    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    await _callback(async_client, user_id, f"cancel:{action.confirmation_token}")

    assert sent[-1] == "Cancelled."
    assert await _workout_count(db_session, user.id) == 0


async def test_log_missing_rpe_saves_null(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/log squat 100 kg for 5, 5, 4")
    assert "RPE" not in sent[-1]

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")

    session = await db_session.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user.id)
        .options(selectinload(WorkoutSession.sets))
    )
    assert session is not None
    assert all(s.rpe is None for s in session.sets)


async def test_log_ambiguous_exercise_clarifies(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/log curl 3x10 at 20 kg")
    assert "Did you mean one of these?" in sent[-1]

    user = await _internal_user(db_session, user_id)
    assert await _pending_action(db_session, user.id) is None


async def test_log_invalid_input_clarifies(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/log bench press 80 kg")
    assert "sets and reps" in sent[-1]

    await _send(async_client, user_id, "/log bench press 3x0 at 80 kg")
    assert "Reps" in sent[-1]


async def test_recommend_insufficient_data(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/recommend bench press")
    assert "Recommendation" in sent[-1]
    assert "Not enough data yet" in sent[-1]


async def test_recommend_unknown_exercise(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(async_client, user_id, "/recommend zzznope")
    assert "couldn't find exercise" in sent[-1]


async def _session_with_sets(db_session, user_id) -> WorkoutSession:
    session = await db_session.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user_id)
        .options(selectinload(WorkoutSession.sets))
    )
    assert session is not None
    return session


def _sorted_sets(session) -> list:
    return sorted(session.sets, key=lambda x: x.set_number)


async def test_log_multiple_exercises_saves_all_sets(
    async_client, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    await _send(
        async_client,
        user_id,
        "/log squat 3x5 at 100 kg; bench press 3x8 at 80 kg, rpe 8",
    )
    assert "I understood:" in sent[-1]
    assert "Squat" in sent[-1]
    assert "Barbell Bench Press" in sent[-1]

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    await _callback(async_client, user_id, f"confirm:{action.confirmation_token}")
    assert sent[-1].startswith("Workout saved (6 set(s)).")

    session = await _session_with_sets(db_session, user.id)
    by_exercise: dict[str, list] = {}
    for s in session.sets:
        by_exercise.setdefault(s.exercise_name, []).append(s)
    assert set(by_exercise) == {"squat", "barbell_bench_press"}
    assert len(by_exercise["squat"]) == 3
    assert len(by_exercise["barbell_bench_press"]) == 3


async def test_log_multiple_exercises_partial_failure_is_atomic(
    async_client, db_session, monkeypatch
):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)

    # Second segment is missing sets/reps -> whole log is rejected.
    await _send(async_client, user_id, "/log squat 3x5 at 100 kg; bench press 80 kg")
    assert "sets and reps" in sent[-1]

    user = await _internal_user(db_session, user_id)
    assert await _pending_action(db_session, user.id) is None


async def test_log_edit_weight_then_confirm(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/log squat 3x5 at 100 kg")

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    token = action.confirmation_token

    await _callback(async_client, user_id, f"edit:{token}")
    assert "What would you like to change?" in sent[-1]

    await _callback(async_client, user_id, f"edit_field:{token}:weight")
    assert "Send the new weight" in sent[-1]

    await _send(async_client, user_id, "110 kg")
    assert "110.0 kg" in sent[-1]
    assert "Save this workout?" in sent[-1]

    await _callback(async_client, user_id, f"confirm:{token}")
    assert sent[-1].startswith("Workout saved (3 set(s)).")

    session = await _session_with_sets(db_session, user.id)
    assert all(s.weight_kg == 110.0 for s in session.sets)


async def test_log_edit_reps_per_set(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/log squat 100 kg for 5, 5, 4")

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    token = action.confirmation_token

    await _callback(async_client, user_id, f"edit_field:{token}:reps")
    await _send(async_client, user_id, "8, 8, 7")
    assert "reps 8, 8, 7" in sent[-1]

    await _callback(async_client, user_id, f"confirm:{token}")
    session = await _session_with_sets(db_session, user.id)
    assert [s.reps for s in _sorted_sets(session)] == [8, 8, 7]


async def test_log_edit_rpe_to_none(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/log squat 3x5 at 100 kg, rpe 8")

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    token = action.confirmation_token

    await _callback(async_client, user_id, f"edit_field:{token}:rpe")
    await _send(async_client, user_id, "none")
    assert "RPE" not in sent[-1]

    await _callback(async_client, user_id, f"confirm:{token}")
    session = await _session_with_sets(db_session, user.id)
    assert all(s.rpe is None for s in session.sets)


async def test_log_edit_date(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/log squat 3x5 at 100 kg")

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    token = action.confirmation_token

    await _callback(async_client, user_id, f"edit_field:{token}:date")
    await _send(async_client, user_id, "2026-08-01")

    await _callback(async_client, user_id, f"confirm:{token}")
    session = await _session_with_sets(db_session, user.id)
    assert session.date == date(2026, 8, 1)


async def test_log_edit_invalid_value_keeps_pending(async_client, db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)

    async def fake_answer(callback_query_id, text=None):
        return None

    monkeypatch.setattr("api.routers.telegram.send_telegram_message", fake_send)
    monkeypatch.setattr("api.routers.telegram.answer_callback_query", fake_answer)

    user_id = next(_next_user_id)
    await _onboard(async_client, user_id)
    await _send(async_client, user_id, "/log squat 3x5 at 100 kg")

    user = await _internal_user(db_session, user_id)
    action = await _pending_action(db_session, user.id)
    token = action.confirmation_token

    await _callback(async_client, user_id, f"edit_field:{token}:weight")
    await _send(async_client, user_id, "not a weight")
    assert "Send the new weight" in sent[-1]

    # The original value is preserved; confirming still saves 100 kg.
    await _callback(async_client, user_id, f"confirm:{token}")
    session = await _session_with_sets(db_session, user.id)
    assert all(s.weight_kg == 100.0 for s in session.sets)
