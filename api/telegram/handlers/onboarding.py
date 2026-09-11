from api.services import onboarding_service as onboarding
from api.telegram.client import send_telegram_message
from api.telegram.handlers.goals import _goal_add
from api.telegram.handlers.profile import handle_profile
from api.telegram.keyboards import onboarding_keyboard


async def handle_start(identity, user, chat_id):
    if identity.onboarding_step not in onboarding.ONBOARDING_STEPS:
        identity.onboarding_step = onboarding.STEP_COMPLETE
    if identity.onboarding_step == onboarding.STEP_COMPLETE:
        await send_telegram_message(chat_id, "Hey, welcome back 👋 Tell me what you trained, ask how you're doing, or say ‘help’ for ideas. No commands needed.")
    else:
        await send_telegram_message(
            chat_id,
            onboarding.onboarding_prompt_for_step(identity.onboarding_step),
            reply_markup=onboarding_keyboard(offer_ai=identity.onboarding_step == onboarding.STEP_AWAITING_WEIGHT),
        )


async def handle_skip(db, identity, user, chat_id):
    await onboarding.advance_onboarding(db, identity, user)
    await send_telegram_message(
        chat_id,
        onboarding.onboarding_prompt_for_step(identity.onboarding_step),
        reply_markup=onboarding_keyboard(),
    )


async def handle_onboard(db, identity, user, chat_id):
    if identity.onboarding_step == onboarding.STEP_COMPLETE:
        identity.onboarding_step = onboarding.STEP_AWAITING_GOAL if user.weight_kg is not None else onboarding.STEP_AWAITING_WEIGHT
    await handle_start(identity, user, chat_id)


async def handle_onboarding_goal(db, identity, user, chat_id, text):
    if text.lower() in {"skip", "later", "not now", "skip goal"}:
        return await handle_skip(db, identity, user, chat_id)
    from api.telegram.parsing import parse_goal_spec
    spec, error = parse_goal_spec(text)
    if error:
        spec, error = parse_goal_spec("weight " + text)
    if error:
        await send_telegram_message(chat_id, onboarding.onboarding_prompt_for_step(onboarding.STEP_AWAITING_GOAL))
    else:
        prefix = "" if text.lower().startswith(("weight ", "frequency ")) else "weight "
        await _goal_add(db, user, chat_id, prefix + text)


async def handle_onboarding_profile(db, identity, user, chat_id, text):
    if text.lower() in {"skip", "later", "not now", "no"}:
        return await handle_skip(db, identity, user, chat_id)
    await send_telegram_message(chat_id, onboarding.onboarding_prompt_for_step(onboarding.STEP_AWAITING_PROFILE_OPTIN))
