"""Explicit, encrypted long-term conversational preferences."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re

from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from api.config import settings
from api.models.db import UserMemory

MAX_MEMORY_CONTENT = 300
MAX_RECALLED_MEMORIES = 10
_SENSITIVE = re.compile(
    r"\b(?:injur(?:y|ies|ed)|pain|diagnos(?:is|ed)|medication|medicine|disease|"
    r"condition|pregnan(?:t|cy)|surgery|allerg(?:y|ies|ic)|disability)\b",
    re.I,
)


def normalize_content(content: str) -> str:
    return " ".join((content or "").strip().split())


def validate_content(content: str) -> str:
    value = normalize_content(content)
    if not 3 <= len(value) <= MAX_MEMORY_CONTENT:
        raise ValueError("Memory must be between 3 and 300 characters")
    if _SENSITIVE.search(value):
        raise ValueError("Sensitive health details need a dedicated consented health-data flow")
    return value


def proposal_payload(content: str) -> dict:
    value = validate_content(content)
    return {
        "category": "preference",
        "encrypted_content": _encrypt(value),
    }


def validate_proposal(payload: dict) -> str:
    if payload.get("category") != "preference":
        raise ValueError("Unsupported memory category")
    encrypted = payload.get("encrypted_content")
    if not isinstance(encrypted, str):
        raise ValueError("Missing encrypted memory")
    return validate_content(_decrypt(encrypted))


def _fingerprint(user_id, content: str) -> str:
    material = user_id.bytes + content.casefold().encode("utf-8")
    return hmac.new(settings.memory_key.encode("ascii"), material, hashlib.sha256).hexdigest()


def _encrypt(content: str) -> str:
    return Fernet(settings.memory_key.encode("ascii")).encrypt(content.encode("utf-8")).decode("ascii")


def _decrypt(content: str) -> str:
    return Fernet(settings.memory_key.encode("ascii")).decrypt(content.encode("ascii")).decode("utf-8")


async def save_proposal(db, user_id, payload: dict) -> None:
    content = validate_proposal(payload)
    now = datetime.now(timezone.utc)
    statement = insert(UserMemory).values(
        user_id=user_id,
        category="preference",
        fingerprint=_fingerprint(user_id, content),
        encrypted_content=payload["encrypted_content"],
        updated_at=now,
    )
    await db.execute(statement.on_conflict_do_update(
        constraint="uq_user_memory_fingerprint",
        set_={"encrypted_content": statement.excluded.encrypted_content, "updated_at": now},
    ))


async def list_memories(db, user_id, limit: int = MAX_RECALLED_MEMORIES) -> list[str]:
    rows = (
        await db.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
            .limit(limit)
        )
    ).all()
    result = []
    for row in rows:
        try:
            result.append(validate_content(_decrypt(row.encrypted_content)))
        except Exception:
            continue
    return result


async def clear_memories(db, user_id) -> int:
    result = await db.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
    return int(result.rowcount or 0)
