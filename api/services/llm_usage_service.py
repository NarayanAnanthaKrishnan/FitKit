"""Persistent daily attempt reservations, serialized across worker processes."""
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from api.config import settings
from api.models.db import LLMUsage, UserPreferences, UserProfile


async def reserve_attempt(session_factory, user_id):
    day = datetime.now(timezone.utc).date()
    async with session_factory() as db:
        # Serialize with account deletion so an in-flight reservation cannot
        # recreate a user's counter after their data has been removed.
        owner = await db.scalar(select(UserProfile.id).where(UserProfile.id == user_id).with_for_update())
        if owner is None:
            return False
        prefs = await db.get(UserPreferences, user_id)
        if prefs is None or not prefs.ai_enabled:
            return False
        # Always lock the global row first to avoid deadlocks.
        rows = []
        for scope, limit in (("global", settings.llm_global_daily_limit), (str(user_id), settings.llm_daily_limit_per_user)):
            await db.execute(insert(LLMUsage).values(scope=scope, day=day, attempts=0).on_conflict_do_nothing())
            row = await db.scalar(select(LLMUsage).where(LLMUsage.scope == scope, LLMUsage.day == day).with_for_update())
            if row.attempts >= limit:
                await db.rollback()
                return False
            rows.append(row)
        for row in rows:
            row.attempts += 1
        await db.commit()
    return True
