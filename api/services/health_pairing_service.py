"""User-owned Health Auto Export pairing tokens.

The raw token is shown to the user once and never stored; only its SHA-256
digest is persisted. Creating a new pairing revokes any previous active
pairing for the same user so a leaked token can always be rotated.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.db import HealthPairing, UserProfile


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


async def create_pairing(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[str, HealthPairing]:
    """Rotate to a fresh active pairing and return ``(raw_token, pairing)``."""
    now = datetime.now(timezone.utc)
    existing = await db.scalars(
        select(HealthPairing).where(
            HealthPairing.user_id == user_id,
            HealthPairing.status == "active",
        )
    )
    for pairing in existing:
        pairing.status = "revoked"
        pairing.revoked_at = now

    token = generate_token()
    pairing = HealthPairing(
        user_id=user_id,
        token_hash=hash_token(token),
        status="active",
    )
    db.add(pairing)
    await db.flush()
    return token, pairing


async def resolve_pairing(
    db: AsyncSession, token: str
) -> HealthPairing | None:
    """Resolve an active pairing by raw token; updates ``last_seen_at``."""
    pairing = await db.scalar(
        select(HealthPairing).where(
            HealthPairing.token_hash == hash_token(token),
            HealthPairing.status == "active",
        )
    )
    if pairing is not None:
        pairing.last_seen_at = datetime.now(timezone.utc)
    return pairing


async def resolve_user_by_pairing(
    db: AsyncSession, token: str
) -> UserProfile | None:
    pairing = await resolve_pairing(db, token)
    if pairing is None:
        return None
    return await db.get(UserProfile, pairing.user_id)


async def revoke_pairings(db: AsyncSession, user_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)
    for pairing in (
        await db.scalars(
            select(HealthPairing).where(
                HealthPairing.user_id == user_id,
                HealthPairing.status == "active",
            )
        )
    ).all():
        pairing.status = "revoked"
        pairing.revoked_at = now
