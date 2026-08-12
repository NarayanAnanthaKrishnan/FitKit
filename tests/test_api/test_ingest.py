import os
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text

from api.models.db import HealthMetric

pytestmark = pytest.mark.asyncio

API_KEY = os.environ["FITKIT_API_KEY"]
INGEST_URL = "/ingest/health"

VALID_PAYLOAD = {
    "data": {
        "metrics": [
            {
                "name": "heart_rate_variability",
                "units": "ms",
                "data": [{"qty": 58.2, "date": "2026-07-25 07:00:00 +0000"}],
            },
            {
                "name": "sleep_analysis",
                "units": "hr",
                "data": [
                    {
                        "date": "2026-07-25",
                        "totalSleep": 7.2,
                        "asleep": 6.8,
                        "core": 4.1,
                        "deep": 1.2,
                        "rem": 1.5,
                        "sleepStart": "2026-07-24 23:10:00 +0000",
                        "sleepEnd": "2026-07-25 06:45:00 +0000",
                        "inBed": 7.5,
                    }
                ],
            },
        ]
    }
}


@pytest_asyncio.fixture(autouse=True)
async def _clean_health_metrics(db_session_factory):
    async with db_session_factory() as session:
        await session.execute(text("TRUNCATE TABLE health_metrics"))
        await session.commit()


def _auth_headers(**extra):
    headers = {"X-API-Key": API_KEY}
    headers.update(extra)
    return headers


async def _metric_rows(db_session):
    result = await db_session.execute(select(HealthMetric))
    return result.scalars().all()


class TestIngestHealth:
    async def test_valid_payload_creates_rows(
        self, async_client: AsyncClient, db_session
    ):
        resp = await async_client.post(
            INGEST_URL, json=VALID_PAYLOAD, headers=_auth_headers()
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["inserted"] == 2
        assert data["skipped"] == 0
        assert data["skipped_reasons"] == []

        rows = await _metric_rows(db_session)
        assert len(rows) == 2
        by_type = {r.metric_type: r for r in rows}
        assert by_type["hrv"].value == 58.2
        assert by_type["hrv"].timestamp == datetime(
            2026, 7, 25, 7, 0, tzinfo=timezone.utc
        )
        assert by_type["hrv"].source == "apple_watch"
        assert by_type["sleep_hours"].value == 6.8
        assert by_type["sleep_hours"].timestamp == datetime(
            2026, 7, 25, 0, 0, tzinfo=timezone.utc
        )

    async def test_same_payload_twice_is_idempotent(
        self, async_client: AsyncClient, db_session
    ):
        resp1 = await async_client.post(
            INGEST_URL, json=VALID_PAYLOAD, headers=_auth_headers()
        )
        assert resp1.json()["inserted"] == 2

        resp2 = await async_client.post(
            INGEST_URL, json=VALID_PAYLOAD, headers=_auth_headers()
        )
        assert resp2.status_code == 201
        assert resp2.json()["inserted"] == 0
        assert len(await _metric_rows(db_session)) == 2

    async def test_missing_api_key_returns_401(
        self, async_client: AsyncClient, db_session
    ):
        before = len(await _metric_rows(db_session))
        resp = await async_client.post(INGEST_URL, json=VALID_PAYLOAD)
        assert resp.status_code == 401
        assert len(await _metric_rows(db_session)) == before

    async def test_wrong_api_key_returns_401(self, async_client: AsyncClient):
        resp = await async_client.post(
            INGEST_URL,
            json=VALID_PAYLOAD,
            headers=_auth_headers(**{"X-API-Key": "wrong-key"}),
        )
        assert resp.status_code == 401

    async def test_unrecognized_metric_is_skipped(
        self, async_client: AsyncClient, db_session
    ):
        payload = {
            "data": {
                "metrics": [
                    {"name": "step_count", "units": "count",
                     "data": [{"qty": 9000, "date": "2026-07-25 12:00:00 +0000"}]},
                    *VALID_PAYLOAD["data"]["metrics"],
                ]
            }
        }
        resp = await async_client.post(
            INGEST_URL, json=payload, headers=_auth_headers()
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["inserted"] == 2
        assert data["skipped"] == 1
        assert any("step_count" in r for r in data["skipped_reasons"])

        rows = await _metric_rows(db_session)
        assert {r.metric_type for r in rows} == {"hrv", "sleep_hours"}

    async def test_malformed_entry_skipped_but_siblings_inserted(
        self, async_client: AsyncClient, db_session
    ):
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "heart_rate_variability",
                        "units": "ms",
                        "data": [
                            {"qty": 58.2, "date": "2026-07-25 07:00:00 +0000"},
                            {"date": "2026-07-26 07:00:00 +0000"},
                        ],
                    },
                ]
            }
        }
        resp = await async_client.post(
            INGEST_URL, json=payload, headers=_auth_headers()
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["inserted"] == 1
        assert data["skipped"] == 1
        assert any("missing qty/Avg" in r for r in data["skipped_reasons"])

        rows = await _metric_rows(db_session)
        assert len(rows) == 1
        assert rows[0].value == 58.2

    async def test_resting_heart_rate_maps_to_resting_hr(
        self, async_client: AsyncClient, db_session
    ):
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "resting_heart_rate",
                        "units": "bpm",
                        "data": [{"qty": 54, "date": "2026-07-25 06:00:00 +0000"}],
                    },
                ]
            }
        }
        resp = await async_client.post(
            INGEST_URL, json=payload, headers=_auth_headers()
        )
        assert resp.status_code == 201
        assert resp.json()["inserted"] == 1

        rows = await _metric_rows(db_session)
        assert len(rows) == 1
        assert rows[0].metric_type == "resting_hr"
        assert rows[0].value == 54


    async def test_non_dict_data_does_not_500(self, async_client: AsyncClient):
        resp = await async_client.post(
            INGEST_URL, json={"data": "not-a-dict"}, headers=_auth_headers()
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["inserted"] == 0
        assert data["skipped"] == 1


class TestHealthSummary:
    SUMMARY_URL = "/health/summary"

    async def test_empty_returns_nulls(self, async_client: AsyncClient):
        await async_client.post("/workouts", json={
            "date": "2026-07-25",
            "session_feeling_energy": 3,
            "sets": [
                {"exercise_name": "squat", "set_number": 1, "reps": 5, "weight_kg": 140, "rpe": 8},
            ],
        })
        resp = await async_client.get(self.SUMMARY_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["latest_hrv"] is None
        assert data["latest_sleep_hours"] is None
        assert data["latest_resting_hr"] is None
        assert data["hrv_baseline_7day"] is None
        assert data["as_of"]

    async def test_with_data_returns_values(self, async_client: AsyncClient):
        today = date.today()
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "heart_rate_variability",
                        "units": "ms",
                        "data": [{"qty": 58.2, "date": f"{today} 07:00:00 +0000"}],
                    },
                    {
                        "name": "sleep_analysis",
                        "units": "hr",
                        "data": [
                            {
                                "date": str(today),
                                "totalSleep": 7.2,
                                "asleep": 6.8,
                                "core": 4.1,
                                "deep": 1.2,
                                "rem": 1.5,
                                "sleepStart": f"{today} 23:10:00 +0000",
                                "sleepEnd": f"{today} 06:45:00 +0000",
                                "inBed": 7.5,
                            }
                        ],
                    },
                ]
            }
        }
        await async_client.post(INGEST_URL, json=payload, headers=_auth_headers())
        resp = await async_client.get(self.SUMMARY_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["latest_hrv"] == 58.2
        assert data["latest_sleep_hours"] == 6.8
        assert data["latest_resting_hr"] is None
        assert data["hrv_baseline_7day"] == 58.2

    async def test_hrv_baseline_averages_multiple_days(
        self, async_client: AsyncClient
    ):
        today = date.today()
        yesterday = today - timedelta(days=1)
        payload = {
            "data": {
                "metrics": [
                    {
                        "name": "heart_rate_variability",
                        "units": "ms",
                        "data": [
                            {"qty": 60.0, "date": f"{yesterday} 07:00:00 +0000"},
                            {"qty": 70.0, "date": f"{today} 07:00:00 +0000"},
                        ],
                    },
                ]
            }
        }
        await async_client.post(INGEST_URL, json=payload, headers=_auth_headers())
        resp = await async_client.get(self.SUMMARY_URL)
        data = resp.json()
        assert data["latest_hrv"] == 70.0
        assert data["hrv_baseline_7day"] == 65.0
