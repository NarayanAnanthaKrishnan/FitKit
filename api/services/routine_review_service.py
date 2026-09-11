"""User-scoped review of explicitly supplied exercises.

This service never selects exercises. It resolves the user's own list and asks
the deterministic recommendation engine what the recorded history supports.
"""
from __future__ import annotations

from api.services import recommendation_service, workout_service


async def review_exercises(db, user_id, queries: list[str]) -> dict:
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for query in queries[:8]:
        canonical, candidates = await workout_service.resolve_exercise(db, query)
        if canonical is None:
            return {
                "ok": False,
                "query": query,
                "candidates": candidates,
                "exercises": [],
            }
        if canonical in seen:
            continue
        seen.add(canonical)
        exercise = await workout_service.get_exercise(db, canonical)
        resolved.append((canonical, exercise.display_name if exercise else canonical))

    reviewed = []
    for canonical, display_name in resolved:
        result = await recommendation_service.get_recommendation(db, user_id, canonical)
        reviewed.append({
            "name": canonical,
            "display_name": display_name,
            "decision": result.decision.value,
            "target_reps": result.target_reps,
            "suggested_load_kg": result.suggested_load_kg,
            "missing_inputs": list(dict.fromkeys(result.missing_inputs)),
            "recovery_override": result.recovery_override,
        })
    return {"ok": True, "exercises": reviewed}
