"""Build the small, user-scoped context supplied to conversational planning."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.models.db import ExerciseTaxonomy, FitnessGoal, WorkoutSession
from api.services import conversation_service, conversation_state_service
from api.services.memory_service import list_memories
from api.services.preferences_service import get_preferences, local_today

MAX_CONTEXT_GOALS = 5
MAX_CONTEXT_WORKOUTS = 3


async def build_agent_context(db, identity, user_id) -> dict:
    """Return bounded context; structured domain rows remain the source of truth."""
    preferences = await get_preferences(db, user_id)
    today = await local_today(db, user_id)
    state, state_payload = await conversation_state_service.get_state(db, user_id)
    goals = (
        await db.scalars(
            select(FitnessGoal)
            .where(FitnessGoal.user_id == user_id, FitnessGoal.status == "active")
            .order_by(FitnessGoal.created_at.desc())
            .limit(MAX_CONTEXT_GOALS)
        )
    ).all()
    workouts = (
        await db.scalars(
            select(WorkoutSession)
            .where(WorkoutSession.user_id == user_id, WorkoutSession.date <= today)
            .order_by(WorkoutSession.date.desc(), WorkoutSession.id.desc())
            .limit(MAX_CONTEXT_WORKOUTS)
            .options(selectinload(WorkoutSession.sets))
        )
    ).all()
    exercise_names = {item.exercise_name for workout in workouts for item in workout.sets}
    taxonomy_rows = (await db.execute(
        select(
            ExerciseTaxonomy.name,
            ExerciseTaxonomy.display_name,
            ExerciseTaxonomy.muscle_group,
        ).where(
            ExerciseTaxonomy.name.in_(exercise_names)
        )
    )).all() if exercise_names else []
    display_names = {row.name: row.display_name for row in taxonomy_rows}
    muscle_groups = {row.name: row.muscle_group for row in taxonomy_rows}

    safe_state = None
    if state is not None and state.kind in {"session_focus", "routine_planning", "routine_logging"}:
        safe_state = {
            "kind": state.kind,
            "focus": str((state_payload or {}).get("focus", ""))[:50],
            "stage": str((state_payload or {}).get("stage", ""))[:30],
            "equipment": str((state_payload or {}).get("equipment", ""))[:50],
            "exercise_names": [
                str(name)[:100]
                for name in (state_payload or {}).get("exercise_names", [])[:8]
            ],
        }
    return {
        "pending_onboarding_step": identity.onboarding_step,
        "today": today.isoformat(),
        "timezone": preferences.timezone,
        "units": preferences.units,
        "recent_turns": await conversation_service.recent_context(db, user_id),
        "conversation_state": safe_state,
        "context_provenance": {
            "recent_turns": "unverified_chat",
            "confirmed_preferences": "confirmed_memory",
            "active_goals": "recorded",
            "recent_routine": "recorded",
        },
        "memory": {
            "confirmed_preferences": await list_memories(db, user_id),
            "active_goals": [
                {
                    "type": goal.goal_type,
                    "target": goal.target_value,
                    "unit": goal.unit,
                    "target_date": goal.target_date.isoformat() if goal.target_date else None,
                }
                for goal in goals
            ],
            "recent_routine": [
                {
                    "date": workout.date.isoformat(),
                    "exercises": list(dict.fromkeys(
                        display_names.get(item.exercise_name, item.exercise_name)
                        for item in workout.sets
                    )),
                    "muscle_groups": list(dict.fromkeys(
                        muscle_groups.get(item.exercise_name, "unknown")
                        for item in workout.sets
                    )),
                }
                for workout in workouts
            ],
        },
    }


async def describe_memory(db, identity, user_id) -> str:
    context = await build_agent_context(db, identity, user_id)
    memory = context["memory"]
    lines = [
        f"Your preferences: {context['units']} units, {context['timezone']} timezone.",
        f"Recent conversation context: {len(context['recent_turns'])} turns retained for up to 24 hours.",
    ]
    goals = memory["active_goals"]
    confirmed = memory["confirmed_preferences"]
    if confirmed:
        lines.append("Confirmed preferences: " + "; ".join(confirmed) + ".")
    else:
        lines.append("Confirmed conversational preferences: none saved.")
    if goals:
        lines.append("Active goals: " + ", ".join(f"{g['type']} {g['target']:g} {g['unit']}" for g in goals) + ".")
    else:
        lines.append("Active goals: none recorded.")
    routine = memory["recent_routine"]
    if routine:
        exercises = list(dict.fromkeys(name for workout in routine for name in workout["exercises"]))
        lines.append("Recent routine exercises: " + ", ".join(exercises[:12]) + ".")
    else:
        lines.append("Recent routine: no workouts recorded yet.")
    if context["conversation_state"]:
        lines.append(f"Current conversation focus: {context['conversation_state']['focus']}.")
    lines.append("Workouts, goals, profile, and health records stay in their structured tables; chat memory is not a permanent transcript.")
    return "\n".join(lines)
