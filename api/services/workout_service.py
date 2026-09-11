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
from api.commands import WorkoutCommand
from api.services.preferences_service import local_today
from api.services.audit_service import audit

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
    session_feeling_energy: int | None = None,
    session_feeling_soreness: list[str] | None = None,
    session_feeling_mood: Optional[str] = None,
    watch_data_available: bool = False,
) -> WorkoutSession:
    """Persist a workout session and its sets. Raises ``ValueError`` on an
    unknown exercise; callers translate that to their own error contract."""
    command = WorkoutCommand.model_validate({"date": workout_date, "sets": sets})
    if session_feeling_energy is not None and (type(session_feeling_energy) is not int or not 1 <= session_feeling_energy <= 5):
        raise ValueError("Energy must be an explicit whole number from 1 to 5")
    if command.date > await local_today(db, user_id):
        raise ValueError("A completed workout cannot be in the future.")
    sets = [s.model_dump(exclude_none=True) for s in command.sets]
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
    audit(db, user_id, "log_workout", {"workout_id": str(session.id), "sets": len(sets)})
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
        .where(WorkoutSession.user_id == user_id,
               WorkoutSession.sets.any(ExerciseSet.exercise_name == exercise_name))
        .order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc())
        .limit(limit)
        .options(selectinload(WorkoutSession.sets))
    )
    sessions = (await db.scalars(stmt)).all()
    return list(sessions)


async def correct_workout(db, user_id, workout_id, expected_revision, workout_date, sets):
    command = WorkoutCommand.model_validate({"date": workout_date, "sets": sets})
    if command.date > await local_today(db, user_id):
        raise ValueError("A completed workout cannot be in the future")
    session = await db.scalar(select(WorkoutSession).where(WorkoutSession.id == workout_id, WorkoutSession.user_id == user_id)
        .with_for_update().options(selectinload(WorkoutSession.sets)).execution_options(populate_existing=True))
    if session is None or session.revision != expected_revision:
        raise ValueError("Workout changed; create a fresh correction preview")
    for item in command.sets:
        if await db.get(ExerciseTaxonomy, item.exercise_name) is None:
            raise ValueError("Unknown exercise")
    previous = {"date": session.date.isoformat(), "revision": session.revision,
                "sets": [{"exercise_name": s.exercise_name, "reps": s.reps, "weight_kg": s.weight_kg, "rpe": s.rpe,
                          "rest_seconds": s.rest_seconds, "avg_heart_rate": s.avg_heart_rate} for s in session.sets]}
    session.date = command.date
    session.revision += 1
    session.sets = [ExerciseSet(**{**item.model_dump(exclude_none=True), "set_number": index}) for index, item in enumerate(command.sets, 1)]
    audit(db, user_id, "correct_workout", {"workout_id": str(session.id), "previous": previous})
    await db.flush()
    return session
