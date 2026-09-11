"""User-local time and explicit preferences, shared across adapters."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import UserPreferences


async def get_preferences(db: AsyncSession, user_id: uuid.UUID) -> UserPreferences:
    row = await db.get(UserPreferences, user_id)
    if row is not None:
        return row
    return UserPreferences(user_id=user_id, timezone="UTC", units="kg", ai_enabled=False)


def validate_preference(field: str, value: str) -> str | bool:
    if field == "timezone":
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use an IANA timezone, e.g. America/New_York.") from None
        return value
    if field == "units" and value in {"kg", "lb"}:
        return value
    if field == "ai" and value in {"on", "off"}:
        return value == "on"
    raise ValueError("Use timezone <IANA zone>, units kg|lb, or ai on|off.")


async def set_preference(db: AsyncSession, user_id: uuid.UUID, field: str, value: str) -> None:
    parsed = validate_preference(field, value)
    changes = {"ai_enabled" if field == "ai" else field: parsed}
    if field == "ai":
        changes["ai_consent_at"] = datetime.now(timezone.utc) if parsed else None
    await db.execute(insert(UserPreferences).values(user_id=user_id, **changes).on_conflict_do_update(index_elements=["user_id"], set_=changes))
    if field == "ai" and not parsed:
        from api.services.conversation_service import clear_context
        await clear_context(db, user_id)


async def local_today(db: AsyncSession, user_id: uuid.UUID) -> date:
    prefs = await get_preferences(db, user_id)
    return datetime.now(ZoneInfo(prefs.timezone)).date()


def day_bounds(day: date, zone: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(zone)
    return (datetime.combine(day, time.min, tz).astimezone(timezone.utc),
            datetime.combine(day + timedelta(days=1), time.min, tz).astimezone(timezone.utc))
