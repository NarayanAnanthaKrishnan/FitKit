import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.dependencies.auth import get_current_user
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.db import HealthMetric, UserProfile
from api.schemas import HealthIngestResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

METRIC_NAME_MAP = {
    "heart_rate_variability": "hrv",
    "resting_heart_rate": "resting_hr",
    "sleep_analysis": "sleep_hours",
}

SOURCE = "apple_watch"


def _normalise_metric_name(raw: str) -> str:
    return "_".join((raw or "").strip().lower().split())


def _parse_timestamp(raw: str) -> datetime:
    value = (raw or "").strip()
    if not value:
        raise ValueError("empty timestamp")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = datetime.fromisoformat(
            value.replace(" +", "+").replace(" -", "-").replace(" ", "T", 1)
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


_VALUE_KEYS = ("qty", "avg", "Avg", "value")


def _entry_value(entry: dict, metric_type: str) -> float | None:
    if metric_type == "sleep_hours":
        for key in ("asleep", "sleepDuration", "qty", "avg", "Avg"):
            value = entry.get(key)
            if value is not None:
                return value
        return None
    for key in _VALUE_KEYS:
        if key in entry:
            return entry.get(key)
    return None


@router.post("/health", response_model=HealthIngestResponse, status_code=201)
async def ingest_health(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: UserProfile = Depends(get_current_user),
):
    rows_to_insert = []
    skipped = 0
    skipped_reasons: list[str] = []

    data = payload.get("data")
    metrics = data.get("metrics", []) if isinstance(data, dict) else None
    if not isinstance(metrics, list):
        skipped += 1
        skipped_reasons.append("data.metrics is not a list")
        metrics = []

    metric_names = [
        _normalise_metric_name(str(m.get("name") or ""))
        for m in metrics
        if isinstance(m, dict)
    ]
    seen_names = sorted({n for n in metric_names if n})
    if seen_names:
        logger.info("Received health metrics: %s", ", ".join(seen_names))

    for metric_obj in metrics:
        if not isinstance(metric_obj, dict):
            skipped += 1
            skipped_reasons.append("non-object metric entry")
            continue

        raw_name = _normalise_metric_name(str(metric_obj.get("name") or ""))
        metric_type = METRIC_NAME_MAP.get(raw_name)
        if metric_type is None:
            skipped += 1
            skipped_reasons.append(f"unmapped metric '{raw_name}'")
            continue

        data_entries = metric_obj.get("data", [])
        if not isinstance(data_entries, list):
            skipped += 1
            skipped_reasons.append(f"'{raw_name}' data is not a list")
            continue

        for entry in data_entries:
            if not isinstance(entry, dict):
                skipped += 1
                skipped_reasons.append(f"'{raw_name}' non-object entry")
                continue

            value = _entry_value(entry, metric_type)
            if value is None:
                skipped += 1
                skipped_reasons.append(
                    f"'{raw_name}' entry missing qty/Avg (keys: {sorted(entry)})"
                )
                continue

            try:
                timestamp = _parse_timestamp(entry.get("date"))
                value_float = float(value)
            except (TypeError, ValueError) as exc:
                skipped += 1
                skipped_reasons.append(f"'{raw_name}' entry unparseable: {exc}")
                continue

            rows_to_insert.append(
                {
                    "user_id": user.id,
                    "metric_type": metric_type,
                    "timestamp": timestamp,
                    "value": value_float,
                    "source": SOURCE,
                }
            )

    inserted = 0
    if rows_to_insert:
        stmt = pg_insert(HealthMetric).values(rows_to_insert)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["user_id", "metric_type", "timestamp", "source"]
        )
        result = await db.execute(stmt)
        inserted = result.rowcount

    for reason in skipped_reasons:
        logger.warning("Skipped health metric entry: %s", reason)

    return HealthIngestResponse(
        inserted=inserted,
        skipped=skipped,
        skipped_reasons=skipped_reasons,
    )
