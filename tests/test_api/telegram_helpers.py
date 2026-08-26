"""Shared Telegram webhook test helpers.

Weight logging now requires inline-button confirmation, so onboarding helpers
across the API tests confirm the pending ``record_weight`` action after the
weight message. The confirmation token is resolved from a dedicated session
because the raw token only exists in the bot's keyboard markup.
"""

import itertools

from httpx import AsyncClient
from sqlalchemy import select

from api.models.db import AgentAction, TelegramIdentity

SECRET_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret"}

_next_cb_update_id = itertools.count(900000)


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


async def post_callback(async_client: AsyncClient, user_id: int, data: str):
    return await async_client.post(
        "/integrations/telegram/webhook",
        json=cb_update(next(_next_cb_update_id), user_id, data),
        headers=SECRET_HEADERS,
    )


async def _resolve_and_post(
    async_client: AsyncClient,
    user_id: int,
    *,
    action_type: str,
    prefix: str,
):
    from tests.test_api.conftest import TestSessionFactory

    # The raw token lives only in the DB; resolve it with an isolated session
    # so callers do not have to thread one through every onboarding call site.
    async with TestSessionFactory() as session:
        internal_user_id = await session.scalar(
            select(TelegramIdentity.user_id).where(
                TelegramIdentity.telegram_user_id == user_id
            )
        )
        assert internal_user_id is not None
        token = await session.scalar(
            select(AgentAction.confirmation_token)
            .where(
                AgentAction.user_id == internal_user_id,
                AgentAction.action_type == action_type,
                AgentAction.status == "pending_confirmation",
            )
            .order_by(AgentAction.created_at.desc())
            .limit(1)
        )
        assert token is not None, f"no pending {action_type} action"
    return await post_callback(async_client, user_id, f"{prefix}:{token}")


async def confirm_latest_weight(async_client: AsyncClient, user_id: int):
    """Click Save on the most recent pending record_weight preview."""
    return await _resolve_and_post(
        async_client, user_id, action_type="record_weight", prefix="confirm"
    )


async def cancel_latest_weight(async_client: AsyncClient, user_id: int):
    """Click Cancel on the most recent pending record_weight preview."""
    return await _resolve_and_post(
        async_client, user_id, action_type="record_weight", prefix="cancel"
    )
