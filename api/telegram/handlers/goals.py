from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import UserProfile
from api.services.goal_service import complete_goal, delete_goal, get_goal_by_ref, list_goals
from api.telegram.agent_actions import record_agent_action
from api.telegram.client import send_telegram_message
from api.telegram.keyboards import confirm_cancel_keyboard
from api.telegram.parsing import goal_preview, parse_goal_spec
from api.telegram.tokens import new_token


async def handle_goals(
    db: AsyncSession, user: UserProfile, chat_id: int, text: str
) -> None:
    parts = text.split(maxsplit=1)
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not rest:
        await _send_goal_list(db, user, chat_id)
        return

    sub, _, arg = rest.partition(" ")
    arg = arg.strip()
    if sub == "add":
        await _goal_add(db, user, chat_id, arg)
    elif sub == "complete":
        await _goal_complete(db, user, chat_id, arg)
    elif sub == "remove":
        await _goal_remove(db, user, chat_id, arg)
    else:
        await send_telegram_message(
            chat_id,
            "Usage: /goals [add <goal> | complete <ref> | remove <ref>]",
        )


async def _send_goal_list(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    goals = await list_goals(db, user.id)
    if not goals:
        await send_telegram_message(
            chat_id,
            "You have no goals yet.\n"
            "Examples:\n"
            "  /goals add weight 75 kg by 2026-12-31\n"
            "  /goals add frequency 3 per week",
        )
        return

    lines = ["Your goals:"]
    for goal in goals:
        ref = str(goal.id)[:8]
        if goal.goal_type == "weight":
            target = f"{goal.target_value} {goal.unit}"
            if goal.target_date:
                target += f" by {goal.target_date}"
            lines.append(f"  {ref} · weight {target} ({goal.status})")
        else:
            lines.append(
                f"  {ref} · {goal.target_value:.0f} sessions/week ({goal.status})"
            )
    await send_telegram_message(chat_id, "\n".join(lines))


async def _goal_add(db: AsyncSession, user: UserProfile, chat_id: int, arg: str) -> None:
    spec, error = parse_goal_spec(arg)
    if error:
        await send_telegram_message(chat_id, error)
        return

    payload = {
        "goal_type": spec["goal_type"],
        "target_value": spec["target_value"],
        "unit": spec["unit"],
        "target_date": spec["target_date"].isoformat() if spec["target_date"] else None,
    }
    token = new_token()
    await record_agent_action(
        db, user.id, "create_goal", payload, confirmation_token=token
    )
    await send_telegram_message(
        chat_id,
        goal_preview(spec),
        reply_markup=confirm_cancel_keyboard(token),
    )


async def _goal_complete(
    db: AsyncSession, user: UserProfile, chat_id: int, ref: str
) -> None:
    goal = await get_goal_by_ref(db, user.id, ref)
    if goal is None:
        await send_telegram_message(
            chat_id, f"No goal matches '{ref}'. Use /goals to list them."
        )
        return
    await complete_goal(db, user.id, goal.id)
    await send_telegram_message(chat_id, f"Goal {ref} marked complete.")


async def _goal_remove(
    db: AsyncSession, user: UserProfile, chat_id: int, ref: str
) -> None:
    goal = await get_goal_by_ref(db, user.id, ref)
    if goal is None:
        await send_telegram_message(
            chat_id, f"No goal matches '{ref}'. Use /goals to list them."
        )
        return
    token = new_token()
    await record_agent_action(
        db,
        user.id,
        "delete_goal",
        {"goal_id": str(goal.id), "ref": ref},
        confirmation_token=token,
    )
    await send_telegram_message(
        chat_id,
        f"Remove goal {ref}?",
        reply_markup=confirm_cancel_keyboard(token, "Remove"),
    )
