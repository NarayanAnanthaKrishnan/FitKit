"""Short-lived, revocable, user-scoped dashboard access links."""

import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import DashboardLink, UserProfile
from api.services.health_pairing_service import generate_token, hash_token

DEFAULT_TTL_SECONDS = 900  # 15 minutes


def _ttl_seconds() -> int:
    raw = os.getenv("DASHBOARD_LINK_TTL_SECONDS")
    try:
        return int(raw) if raw else DEFAULT_TTL_SECONDS
    except ValueError:
        return DEFAULT_TTL_SECONDS


async def create_link(
    db: AsyncSession, user_id: uuid.UUID, ttl_seconds: int | None = None
) -> tuple[str, DashboardLink]:
    token = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=ttl_seconds if ttl_seconds is not None else _ttl_seconds()
    )
    link = DashboardLink(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=expires_at,
    )
    db.add(link)
    await db.flush()
    return token, link


async def resolve_user_by_token(
    db: AsyncSession, token: str
) -> UserProfile | None:
    now = datetime.now(timezone.utc)
    link = await db.scalar(
        select(DashboardLink).where(
            DashboardLink.token_hash == hash_token(token),
            DashboardLink.revoked_at.is_(None),
            DashboardLink.expires_at > now,
        )
    )
    if link is None:
        return None
    link.last_used_at = now
    return await db.get(UserProfile, link.user_id)


async def revoke_links(db: AsyncSession, user_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)
    for link in (
        await db.scalars(
            select(DashboardLink).where(
                DashboardLink.user_id == user_id,
                DashboardLink.revoked_at.is_(None),
            )
        )
    ).all():
        link.revoked_at = now
