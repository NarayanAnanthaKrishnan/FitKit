"""Optional onboarding progression; deletion is an independent expiring action."""
from sqlalchemy import select
from api.models.db import TelegramIdentity

STEP_AWAITING_WEIGHT = "awaiting_weight"
STEP_AWAITING_GOAL = "awaiting_goal"
STEP_AWAITING_PROFILE_OPTIN = "awaiting_profile_optin"
STEP_COMPLETE = "complete"
ONBOARDING_STEPS = (STEP_AWAITING_WEIGHT, STEP_AWAITING_GOAL, STEP_AWAITING_PROFILE_OPTIN, STEP_COMPLETE)


async def is_onboarding_complete(db, user_id):
    step = await db.scalar(select(TelegramIdentity.onboarding_step).where(TelegramIdentity.user_id == user_id))
    return step == STEP_COMPLETE


async def advance_onboarding(db, identity, user):
    current = identity.onboarding_step
    index = ONBOARDING_STEPS.index(current) if current in ONBOARDING_STEPS else len(ONBOARDING_STEPS) - 1
    identity.onboarding_step = ONBOARDING_STEPS[min(index + 1, len(ONBOARDING_STEPS) - 1)]
    return identity.onboarding_step


async def mark_onboarding_complete(identity):
    identity.onboarding_step = STEP_COMPLETE


mark_profile_optin_seen = mark_onboarding_complete


def onboarding_prompt_for_step(step):
    return {
        STEP_AWAITING_WEIGHT: "Hey — I'm FitKit, your training sidekick 👋 You can talk to me normally; commands like /log are just shortcuts. Weight is optional: send something like ‘80 kg’, or skip it for now. Flexible AI chat is optional and needs your permission.",
        STEP_AWAITING_GOAL: "Cool. What would you like to accomplish? Try ‘I want to weigh 75 kg by 2026-12-31’ or ‘I want to train 3 times a week’. You can also say ‘skip’.",
        STEP_AWAITING_PROFILE_OPTIN: "Last setup question. Age and sex are optional. Try ‘I'm 30 years old’ or ‘I'm female’. Saying ‘skip’ is totally fine.",
        STEP_COMPLETE: "All set. Tell me what you trained, or ask how you're doing.",
    }.get(step)
