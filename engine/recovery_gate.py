HRV_TREND_THRESHOLD = 0.85
HRV_SEVERE_THRESHOLD = 0.70
MIN_SLEEP_HOURS = 6.0
SEVERE_SLEEP_HOURS = 4.0
MIN_RECOVERY_DAYS_FOR_TRIGGER = 2


def check_recovery(
    hrv_readings: list[float | None],
    hrv_baseline_7day: float | None,
    sleep_readings: list[float | None],
) -> str | None:
    if not hrv_readings or hrv_baseline_7day is None or hrv_baseline_7day <= 0:
        hrv_trend_bad = False
        hrv_severe = False
    else:
        below_trend = sum(
            1 for h in hrv_readings
            if h is not None and h < hrv_baseline_7day * HRV_TREND_THRESHOLD
        )
        hrv_trend_bad = below_trend >= MIN_RECOVERY_DAYS_FOR_TRIGGER
        hrv_severe = any(
            h is not None and h < hrv_baseline_7day * HRV_SEVERE_THRESHOLD
            for h in hrv_readings
        )

    if not sleep_readings:
        sleep_trend_bad = False
        sleep_severe = False
    else:
        low_sleep_days = sum(1 for s in sleep_readings if s is not None and s < MIN_SLEEP_HOURS)
        sleep_trend_bad = low_sleep_days >= MIN_RECOVERY_DAYS_FOR_TRIGGER
        sleep_severe = any(s is not None and s < SEVERE_SLEEP_HOURS for s in sleep_readings)

    if hrv_severe:
        return "cap_intensity_severe_hrv_drop"
    if sleep_severe:
        return "cap_intensity_severe_sleep_deprivation"
    if hrv_trend_bad:
        return "cap_intensity_hrv_trend"
    if sleep_trend_bad:
        return "cap_intensity_sleep_trend"

    return None
