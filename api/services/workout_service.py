"""Shared workout domain service.

Used by both the REST workouts route and the Telegram adapter so that workout
logging, history, and exercise-name resolution stay consistent and user-scoped.
"""

import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from api.models.db import ExerciseSet, ExerciseTaxonomy, WorkoutSession
from api.services.workout_parser import ALIASES, compact

MAX_CANDIDATES = 6


async def get_exercise(
    db: AsyncSession, name: str
) -> ExerciseTaxonomy | None:
    return await db.get(ExerciseTaxonomy, name)


async def resolve_exercise(
    db: AsyncSession, query: str
) -> tuple[str | None, list[str]]:
    """Resolve a free-text exercise name to a canonical taxonomy name.

    Returns ``(canonical_name, [])`` on success, ``(None, candidates)`` when the
    query is ambiguous (caller should ask for clarification), or ``(None, [])``
    when no taxonomy match exists.
    """
    q = (query or "").strip()
    if not q:
        return None, []

    alias = ALIASES.get(q.lower())
    if alias:
        return alias, []

    rows = (
        await db.execute(
            select(ExerciseTaxonomy.name, ExerciseTaxonomy.display_name)
        )
    ).all()
    if not rows:
        return None, []

    compact_q = compact(q)
    if not compact_q:
        return None, []

    # 1) Exact match on canonical name or display name.
    for name, display in rows:
        if compact(name) == compact_q or compact(display) == compact_q:
            return name, []

    # 2) De-pluralized exact match ("squats" -> "squat").
    if compact_q.endswith("s"):
        for name, display in rows:
            if compact(name) == compact_q[:-1] or compact(display) == compact_q[:-1]:
                return name, []

    # 3) Substring match in either direction; collect unique candidates.
    candidates: list[str] = []
    for name, display in rows:
        if compact_q in compact(name) or compact(name) in compact_q or compact_q in compact(display):
            if name not in candidates:
                candidates.append(name)

    if len(candidates) == 1:
        return candidates[0], []
    if len(candidates) > 1:
        return None, candidates[:MAX_CANDIDATES]
    return None, []


async def create_workout(
    db: AsyncSession,
    user_id: uuid.UUID,
    workout_date: date,
    sets: list[dict[str, Any]],
    *,
    session_feeling_energy: int = 3,
    session_feeling_soreness: list[str] | None = None,
    session_feeling_mood: Optional[str] = None,
    watch_data_available: bool = False,
) -> WorkoutSession:
    """Persist a workout session and its sets. Raises ``ValueError`` on an
    unknown exercise; callers translate that to their own error contract."""
    for s in sets:
        if await db.get(ExerciseTaxonomy, s["exercise_name"]) is None:
            raise ValueError(f"Unknown exercise: '{s['exercise_name']}'")

    session = WorkoutSession(
        user_id=user_id,
        date=workout_date,
        session_feeling_energy=session_feeling_energy,
        session_feeling_soreness=",".join(session_feeling_soreness or []),
        session_feeling_mood=session_feeling_mood,
        watch_data_available=watch_data_available,
    )
    db.add(session)

    db_sets: list[ExerciseSet] = []
    for index, s in enumerate(sets, start=1):
        db_sets.append(
            ExerciseSet(
                exercise_name=s["exercise_name"],
                set_number=s.get("set_number", index),
                reps=s["reps"],
                weight_kg=s["weight_kg"],
                rpe=s.get("rpe"),
                rest_seconds=s.get("rest_seconds"),
                avg_heart_rate=s.get("avg_heart_rate"),
            )
        )
    # Assign the collection (rather than appending to an unloaded relationship)
    # so the sets are attached via cascade without an async lazy-load.
    session.sets = db_sets
    await db.flush()
    return session


async def get_workout(
    db: AsyncSession, user_id: uuid.UUID, workout_id: uuid.UUID
) -> WorkoutSession | None:
    stmt = (
        select(WorkoutSession)
        .where(
            WorkoutSession.id == workout_id,
            WorkoutSession.user_id == user_id,
        )
        .options(joinedload(WorkoutSession.sets))
    )
    return (await db.scalars(stmt)).unique().first()


async def exercise_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    exercise_name: str,
    limit: int,
) -> list[WorkoutSession]:
    """Return sessions (with sets eager-loaded) containing the exercise, newest first."""
    stmt = (
        select(WorkoutSession)
        .where(WorkoutSession.user_id == user_id)
        .order_by(WorkoutSession.date.desc())
        .limit(limit)
        .options(selectinload(WorkoutSession.sets))
    )
    sessions = (await db.scalars(stmt)).all()
    return [
        s
        for s in sessions
        if any(es.exercise_name == exercise_name for es in s.sets)
    ]
