from dataclasses import dataclass, field
from datetime import date

from engine.acwr import acwr_flag, compute_acwr
from engine.overload import OverloadDecision, SessionLog, check_overload
from engine.recovery_gate import check_recovery


@dataclass
class Recommendation:
    decision: OverloadDecision
    acwr_ratio: float | None
    acwr_flag: str
    recovery_override: str | None
    explanation: str
    rule_version: str = "2.0"
    as_of: date | None = None
    target_reps: int | None = None
    missing_inputs: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    freshness: dict = field(default_factory=dict)
    suggested_load_kg: float | None = None


def get_recommendation(
    exercise_history: list[SessionLog],
    target_reps: int | None,
    daily_volume: dict[date, float],
    today: date,
    hrv_readings_last_3days: list[float | None] | None = None,
    hrv_baseline_7day: float | None = None,
    sleep_readings_last_3days: list[float | None] | None = None,
) -> Recommendation:
    base_decision = check_overload(exercise_history, target_reps) if target_reps is not None else OverloadDecision.INSUFFICIENT_DATA

    ratio = compute_acwr(daily_volume, today)
    risk_flag = acwr_flag(ratio)

    hrv = hrv_readings_last_3days if hrv_readings_last_3days is not None else []
    sleep = sleep_readings_last_3days if sleep_readings_last_3days is not None else []

    recovery_override = check_recovery(hrv, hrv_baseline_7day, sleep)

    if recovery_override is not None:
        return Recommendation(
            decision=(OverloadDecision.HOLD if base_decision == OverloadDecision.INCREASE_LOAD else base_decision),
            acwr_ratio=ratio,
            acwr_flag=risk_flag,
            recovery_override=recovery_override,
            explanation=f"Recovery signal overrode training logic: {recovery_override}",
        )

    final_decision = base_decision
    if risk_flag == "elevated_risk" and base_decision == OverloadDecision.INCREASE_LOAD:
        final_decision = OverloadDecision.HOLD

    explanation = (
        f"overload={base_decision.value}, acwr_ratio={ratio}, acwr_flag={risk_flag}"
    )

    return Recommendation(
        decision=final_decision,
        acwr_ratio=ratio,
        acwr_flag=risk_flag,
        recovery_override=None,
        explanation=explanation,
    )
