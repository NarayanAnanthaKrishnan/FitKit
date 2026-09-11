from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import AgentAction, TelegramIdentity, UserProfile
from api.telegram.agent_actions import not_expired
from api.telegram.client import send_telegram_message


async def handle_cancel(
    db: AsyncSession, identity: TelegramIdentity, user: UserProfile, chat_id: int
) -> None:
    if identity.onboarding_step == "awaiting_delete_confirmation":
        identity.onboarding_step = (
            "complete" if user.weight_kg is not None else "awaiting_weight"
        )
        await send_telegram_message(chat_id, "Deletion cancelled. Your data is safe.")
        return

    from api.services.conversation_state_service import clear_state, get_state
    state, _ = await get_state(db, user.id)
    if state is not None:
        await clear_state(db, user.id)
        await send_telegram_message(chat_id, "Cancelled.")
        return

    action = await db.scalar(
        select(AgentAction)
        .where(
            AgentAction.user_id == user.id,
            AgentAction.status == "pending_confirmation",
            not_expired(),
        )
        .order_by(AgentAction.created_at.desc())
        .limit(1)
    )
    if action is not None:
        action.status = "cancelled"
        await send_telegram_message(chat_id, "Deletion cancelled. Your data is safe." if action.action_type == "delete_user" else "Cancelled.")
    else:
        if identity.onboarding_step in (
            "awaiting_goal",
            "awaiting_profile_optin",
        ):
            await send_telegram_message(chat_id, "Nothing to cancel. Send your goal or /skip to continue setup.")
            return
        await send_telegram_message(chat_id, "Nothing to cancel.")
