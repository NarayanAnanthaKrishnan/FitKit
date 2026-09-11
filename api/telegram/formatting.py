"""Shared Telegram message formatters — reuses summary_service shapes."""
from __future__ import annotations

from api.telegram.constants import _DECISION_LABELS
from api.services.units import display_load, format_load


def format_today(snapshot: dict) -> str:
    weight = snapshot.get("weight_kg")
    lines = [f"Weight: {format_load(weight, snapshot.get('units', 'kg'))}" if weight is not None else "Weight: not recorded"]

    health = snapshot.get("health") or {}
    if health.get("has_data"):
        parts = []
        if health["latest_hrv"] is not None:
            parts.append(f"HRV {health['latest_hrv']} ms")
        if health["latest_sleep_hours"] is not None:
            parts.append(f"sleep {health['latest_sleep_hours']} h")
        if health["latest_resting_hr"] is not None:
            parts.append(f"resting HR {health['latest_resting_hr']}")
        lines.append("Recovery: " + (", ".join(parts) if parts else "no recent readings"))
    else:
        lines.append("Recovery: no health data connected yet")

    workout = snapshot.get("last_workout")
    if workout is not None:
        exercises = ", ".join(workout["exercises"]) or "no exercises"
        lines.append(f"Last workout: {workout['date']} ({exercises})")
    else:
        lines.append("Last workout: none logged yet")

    return "Today\n" + "\n".join(lines)


def format_progress(summary: dict) -> str:
    lines = []
    weight = summary["weight"]
    unit = weight.get("units", "kg")
    if weight["latest_kg"] is None:
        lines.append("Weight: no measurements yet")
    else:
        line = f"Weight: {format_load(weight['latest_kg'], unit)}"
        if weight["change_7d"] is not None:
            line += f" (7d: {display_load(weight['change_7d'], unit):+.1f} {unit})"
        if weight["change_30d"] is not None:
            line += f" (30d: {display_load(weight['change_30d'], unit):+.1f} {unit})"
        lines.append(line)

    goals = summary["goals"]
    if not goals:
        lines.append("Goals: none active — tell me a specific weight or weekly training goal when you're ready")
    else:
        lines.append("Goals:")
        for goal in goals:
            if goal["type"] == "frequency":
                lines.append(
                    f"  {goal['ref']} · {goal['current']}/{goal['target']:.0f} "
                    f"{goal['unit']} ({goal['progress_pct']}%)"
                )
            else:
                current = f"{goal['current']:.1f}" if goal["current"] is not None else "?"
                lines.append(
                    f"  {goal['ref']} · {current} {goal['unit']} "
                    f"/ target {goal['target']} {goal['unit']}"
                )

    for week in summary.get("weekly_sessions", []):
        lines.append(f"Week of {week['week_start']}: {week['sessions']} sessions")
    for exercise in summary.get("exercises", []):
        estimate = exercise.get("best_estimated_1rm_kg")
        lines.append(f"{exercise['exercise_name']}: last logged {exercise['latest_date']}")
        if estimate is not None:
            lines.append(f"  Estimated 1RM (sets of up to 12 reps): {format_load(estimate, unit)}; this is an estimate")
        lines.append(f"  Workout ID: {exercise['workout_id']}")
    return "Progress\n" + "\n".join(lines)


def format_health(health: dict) -> str:
    if not health.get("has_data"):
        if any(v.get("conflicting_days") for v in health.get("freshness", {}).values()):
            return "Recent health readings conflict across sources or sleep totals. Check your bridge settings and use one daily source. Recommendations will treat those days as missing."
        return (
            "No health data is connected yet. Connect Health Auto Export or log "
            "health metrics to see HRV, sleep, and resting HR here."
        )
    lines = []
    if health["latest_hrv"] is not None:
        lines.append(f"Latest HRV: {health['latest_hrv']} ms")
    if health["latest_sleep_hours"] is not None:
        lines.append(f"Latest sleep: {health['latest_sleep_hours']} h")
    if health["latest_resting_hr"] is not None:
        lines.append(f"Latest resting HR: {health['latest_resting_hr']} bpm")
    if health["hrv_baseline_7day"] is not None:
        lines.append(f"HRV baseline (7d): {health['hrv_baseline_7day']} ms")
    for kind, value in health.get("freshness", {}).items():
        lines.append(f"{kind}: measured {value['measured_at']}" + (" (stale)" if value["stale"] else ""))
        if value.get("sources"):
            lines.append("  Source: " + ", ".join(value["sources"]))
        if value.get("conflicting_days"):
            lines.append(f"  {value['conflicting_days']} conflicting day(s) excluded; check bridge settings.")
    return "Health\n" + "\n".join(lines)


def format_recommendation(display_name: str, result, unit: str = "kg") -> str:
    lines = [f"Recommendation — {display_name}:"]
    label = _DECISION_LABELS.get(result.decision.value, result.decision.value)
    lines.append(f"Decision: {label}")
    if result.target_reps is not None:
        lines.append(f"Target: {result.target_reps} reps")
    if result.suggested_load_kg is not None:
        lines.append(f"Suggested next load: {format_load(result.suggested_load_kg, unit)}")
    missing = {"target_reps": "Set a rep target first, for example ‘target 8 reps’.", "three_exercise_sessions": "Log this exercise in three sessions to assess progression.", "primary_set_rpe": "Record RPE for the primary sets in your recent sessions."}
    lines.extend(missing[item] for item in result.missing_inputs if item in missing)
    if result.acwr_ratio is not None:
        lines.append(f"Workload ratio: {result.acwr_ratio} (a training heuristic, not an injury prediction)")
    else:
        lines.append("Workload ratio: not enough recorded days.")
    if result.recovery_override is not None:
        lines.append("Recent recovery readings suggest limiting intensity.")
    return "\n".join(lines)


def exercise_clarification(query: str, candidates: list[str]) -> str:
    if candidates:
        return (
            f"I couldn't match '{query}' uniquely. Did you mean one of these?\n"
            + "\n".join(f"  • {c}" for c in candidates)
            + "\nPlease resend with the exact name."
        )
    return (
        f"I couldn't find exercise '{query}'. "
        "Please use a name from the exercise list."
    )


def workout_preview_from_payload(payload: dict) -> str:
    displays = {e["name"]: e["display"] for e in payload.get("exercises", [])}
    lines = [f"Date: {payload['date']} ({payload.get('timezone', 'UTC')})"]
    for index, item in enumerate(payload.get("sets", []), 1):
        name = displays.get(item["exercise_name"], item["exercise_name"])
        rpe = str(item["rpe"]) if item.get("rpe") is not None else "not recorded"
        unit = payload.get("units", "kg")
        load = f"{display_load(item['weight_kg'], unit):g} {unit}" if unit == "kg" else format_load(item["weight_kg"], unit)
        lines.append(f"Set {index}: {name}, {item['reps']} reps at {load}; RPE {rpe}")
    return "I understood:\n" + "\n".join(lines) + "\nSave this workout? Use Edit then 'set 2: 82.5 kg' to change one set."


def _exercise_line(display_name: str, ex_sets: list[dict]) -> str:
    weight = ex_sets[0]["weight_kg"]
    reps = [s["reps"] for s in ex_sets]
    if len(set(reps)) == 1:
        reps_part = f"{len(ex_sets)} sets × {reps[0]} reps"
    else:
        reps_part = "reps " + ", ".join(str(r) for r in reps)

    rpe_values = sorted({s["rpe"] for s in ex_sets if s["rpe"] is not None})
    parts = [display_name, reps_part, f"{weight} kg"]
    if rpe_values:
        parts.append("RPE " + ", ".join(str(r) for r in rpe_values))
    return " — ".join(parts)


def profile_display(user, unit: str = "kg") -> str:
    def fmt(value: object) -> str:
        return str(value) if value is not None else "not set"

    lines = [
        f"Weight: {format_load(user.weight_kg, unit)}"
        if user.weight_kg is not None
        else "Weight: not set",
        f"Age: {fmt(user.age)}",
        f"Sex: {fmt(user.sex)}",
        f"Resting HR: {fmt(user.resting_hr)}",
        f"Max HR: {fmt(user.max_hr)}",
        f"Calibration: {user.personal_calibration_factor}",
    ]
    return (
        "Your profile ✨\n"
        + "\n".join(lines)
        + "\n\nProfile details are optional. You can describe a change naturally when conversation is enabled, or use /profile set <field> <value>. Every change is previewed first."
    )
