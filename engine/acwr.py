from datetime import date, timedelta

ACUTE_WINDOW_DAYS = 7
CHRONIC_WINDOW_DAYS = 28
MIN_DAYS_LOGGED_FOR_CHRONIC = 14
WEEKS_IN_CHRONIC_WINDOW = CHRONIC_WINDOW_DAYS / 7
ELEVATED_RISK_THRESHOLD = 1.5
UNDERTRAINING_THRESHOLD = 0.8


def compute_acwr(daily_volume: dict[date, float], today: date) -> float | None:
    acute_days = [today - timedelta(days=i) for i in range(ACUTE_WINDOW_DAYS)]
    chronic_days = [today - timedelta(days=i) for i in range(CHRONIC_WINDOW_DAYS)]

    days_with_data = sum(1 for d in chronic_days if d in daily_volume)
    if days_with_data < MIN_DAYS_LOGGED_FOR_CHRONIC:
        return None

    acute = sum(daily_volume.get(d, 0) for d in acute_days)
    chronic_total = sum(daily_volume.get(d, 0) for d in chronic_days)
    chronic_avg_weekly = chronic_total / WEEKS_IN_CHRONIC_WINDOW

    if chronic_avg_weekly == 0:
        return None

    return round(acute / chronic_avg_weekly, 2)


def acwr_flag(ratio: float | None) -> str:
    if ratio is None:
        return "insufficient_data"
    if ratio > ELEVATED_RISK_THRESHOLD:
        return "elevated_risk"
    if ratio < UNDERTRAINING_THRESHOLD:
        return "undertraining"
    return "normal"
