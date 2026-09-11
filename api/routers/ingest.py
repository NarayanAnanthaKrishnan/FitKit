"""Health adapters: parse external formats, then call the shared ingestion service."""
import re
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db
from api.dependencies.health_auth import get_ingest_user
from api.models.db import UserProfile
from api.schemas import HealthIngestResponse, ShortcutHealthIngest
from api.services.ingestion_service import ingest_rows, payload_hash, validate_measurement

router = APIRouter(prefix="/ingest", tags=["ingest"])
METRIC_NAME_MAP = {"heart_rate_variability": "hrv", "resting_heart_rate": "resting_hr", "sleep_analysis": "sleep_hours"}
METRIC_UNITS = {"hrv": {"ms"}, "resting_hr": {"bpm", "count/min"}, "sleep_hours": {"hr", "h", "hours"}}


def _normalise_metric_name(raw):
    return "_".join(str(raw or "").strip().lower().split())


def _parse_timestamp(raw):
    if not isinstance(raw, str):
        raise ValueError("invalid_timestamp")
    value = raw.strip()
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        stamp = datetime.fromisoformat(value.replace(" +", "+").replace(" -", "-").replace(" ", "T", 1))
    # Legacy exporter timestamps without offsets retain the documented UTC interpretation.
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def _entry_value(entry, kind):
    keys = ("asleep", "sleepDuration", "qty", "avg", "Avg") if kind == "sleep_hours" else ("qty", "avg", "Avg", "value")
    return next((entry[k] for k in keys if entry.get(k) is not None), None)


@router.post("/health", response_model=HealthIngestResponse, status_code=201)
async def ingest_health(payload: dict, db: AsyncSession = Depends(get_db), user: UserProfile = Depends(get_ingest_user),
                        batch_id: str | None = Header(default=None, alias="X-Ingest-Batch-Id")):
    try:
        fingerprint = payload_hash(payload)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Payload must contain finite JSON values") from None
    if batch_id is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", batch_id):
        raise HTTPException(status_code=422, detail="Invalid batch ID")
    rows, skipped = [], []
    data = payload.get("data")
    metrics = data.get("metrics") if isinstance(data, dict) else None
    if not isinstance(metrics, list):
        metrics = []
        skipped.append("invalid_metrics_list")
    if len(metrics) > 100:
        raise HTTPException(status_code=413, detail="Too many metric groups")
    for metric in metrics:
        if not isinstance(metric, dict):
            skipped.append("invalid_metric_entry")
            continue
        kind = METRIC_NAME_MAP.get(_normalise_metric_name(metric.get("name")))
        if kind is None:
            skipped.append("unmapped_metric")
            continue
        if metric.get("units") is not None and str(metric["units"]).lower() not in METRIC_UNITS[kind]:
            skipped.append("unsupported_unit")
            continue
        entries = metric.get("data", [])
        if not isinstance(entries, list):
            skipped.append("invalid_samples_list")
            continue
        if len(entries) > 5000 or len(rows) + len(entries) > 5000:
            raise HTTPException(status_code=413, detail="Too many samples")
        for entry in entries:
            if not isinstance(entry, dict):
                skipped.append("invalid_sample")
                continue
            try:
                stamp = _parse_timestamp(entry.get("date"))
                value = validate_measurement(kind, _entry_value(entry, kind), stamp)
            except (ValueError, TypeError):
                skipped.append("invalid_value_or_timestamp")
                continue
            rows.append({"user_id": user.id, "metric_type": kind, "timestamp": stamp, "value": value, "source": "apple_watch"})
    key = hashlib.sha256(batch_id.encode()).hexdigest() if batch_id else fingerprint
    return await ingest_rows(db, user.id, "health:" + key, fingerprint, rows, skipped)


@router.post("/shortcut", response_model=HealthIngestResponse, status_code=201)
async def ingest_health_shortcut(payload: ShortcutHealthIngest, db: AsyncSession = Depends(get_db),
                                user: UserProfile = Depends(get_ingest_user)):
    return await _shortcut(db, user, payload)


@router.post("/shortcut/validate")
async def validate_shortcut(payload: ShortcutHealthIngest, db: AsyncSession = Depends(get_db),
                            user: UserProfile = Depends(get_ingest_user)):
    return await _shortcut(db, user, payload, validate_only=True)


async def _shortcut(db, user, payload, validate_only=False):
    if payload.measured_at is None and payload.batch_id is None and not validate_only:
        raise HTTPException(status_code=422, detail="Provide measured_at or a stable batch_id for safe retries")
    measured_at = payload.measured_at or datetime.now(timezone.utc)
    rows = []
    for kind in ("hrv", "resting_hr", "sleep_hours"):
        value = getattr(payload, kind)
        if value is None:
            continue
        try:
            value = validate_measurement(kind, value, measured_at)
        except ValueError:
            raise HTTPException(status_code=422, detail="Measurements require a valid value and a non-future timezone-aware timestamp") from None
        rows.append({"user_id": user.id, "metric_type": kind, "timestamp": measured_at, "value": value, "source": "apple_shortcuts"})
    if not rows:
        raise HTTPException(status_code=422, detail="Provide at least one health metric")
    fingerprint = payload_hash(payload.model_dump(mode="json", exclude={"batch_id"}))
    key = hashlib.sha256(payload.batch_id.encode()).hexdigest() if payload.batch_id else fingerprint
    return await ingest_rows(db, user.id, "shortcut:" + key, fingerprint, rows, [], validate_only=validate_only)
