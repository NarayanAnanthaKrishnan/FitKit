"""Shared validated, user-owned ingestion with stable batch identity."""
import hashlib
import json
import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from api.models.db import HealthMetric, IngestBatch, UserProfile
from api.services.audit_service import audit

METRIC_LIMITS = {"hrv": (0, 300), "resting_hr": (0, 250), "sleep_hours": (0, 24)}


class BatchConflict(ValueError):
    pass


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_measurement(kind, value, stamp):
    if kind not in METRIC_LIMITS or type(value) is bool:
        raise ValueError("invalid_metric")
    value = float(value)
    low, high = METRIC_LIMITS[kind]
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("invalid_value")
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise ValueError("invalid_timestamp")
    return value


async def ingest_rows(db, user_id, batch_id, fingerprint, rows, skipped_reasons, *, validate_only=False):
    if validate_only:
        return {"inserted": 0, "skipped": len(skipped_reasons), "skipped_reasons": skipped_reasons,
                "duplicates": 0, "batch_duplicate": False, "valid": len(rows)}
    await db.scalar(select(UserProfile.id).where(UserProfile.id == user_id).with_for_update())
    existing = await db.get(IngestBatch, (user_id, batch_id))
    if existing is not None:
        if existing.payload_hash != fingerprint:
            raise BatchConflict("Batch ID was already used for different data")
        audit(db, user_id, "ingest_health_duplicate", {"duplicates": existing.result["inserted"] + existing.result["duplicates"]})
        return {**existing.result, "inserted": 0, "duplicates": existing.result["inserted"] + existing.result["duplicates"], "batch_duplicate": True}
    inserted = 0
    if rows:
        result = await db.execute(insert(HealthMetric).values(rows).on_conflict_do_nothing(index_elements=["user_id", "metric_type", "timestamp", "source"]))
        inserted = result.rowcount
    result = {"inserted": inserted, "skipped": len(skipped_reasons), "skipped_reasons": skipped_reasons,
              "duplicates": len(rows) - inserted, "batch_duplicate": False}
    db.add(IngestBatch(user_id=user_id, batch_id=batch_id, payload_hash=fingerprint, result=result))
    audit(db, user_id, "ingest_health", {"inserted": inserted, "duplicates": result["duplicates"], "skipped": result["skipped"]})
    return result
