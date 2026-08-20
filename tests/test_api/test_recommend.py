from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 7, 25)


@pytest_asyncio.fixture(autouse=True)
async def _isolate_workouts(db_session):
    """Recommendation decisions depend on recent workout history, so keep these
    tests independent of workouts seeded by other test modules."""
    await db_session.execute(
        text("TRUNCATE TABLE exercise_sets, workout_sessions CASCADE")
    )
    await db_session.commit()
    yield


class TestRecommend:
    RECOMMEND_URL = "/recommend/barbell_bench_press"

    async def test_unknown_exercise_returns_404(self, async_client: AsyncClient):
        resp = await async_client.get("/recommend/nonexistent_lift")
        assert resp.status_code == 404

    async def test_no_user_returns_insufficient_data(self, async_client: AsyncClient):
        resp = await async_client.get(self.RECOMMEND_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "insufficient_data"

    async def test_fewer_than_3_sessions_returns_insufficient_data(
        self, async_client: AsyncClient
    ):
        await async_client.post("/workouts", json={
            "date": str(TODAY),
            "session_feeling_energy": 4,
            "sets": [
                {"exercise_name": "barbell_bench_press", "set_number": 1, "reps": 8, "weight_kg": 100, "rpe": 7},
            ],
        })
        resp = await async_client.get(self.RECOMMEND_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "insufficient_data"

    async def test_no_health_metrics_still_works(self, async_client: AsyncClient):
        for i in range(3):
            await async_client.post("/workouts", json={
                "date": str(TODAY - timedelta(days=2 - i)),
                "session_feeling_energy": 4,
                "sets": [
                    {"exercise_name": "barbell_bench_press", "set_number": 1, "reps": 8, "weight_kg": 100, "rpe": 7},
                ],
            })
        resp = await async_client.get(self.RECOMMEND_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] in ("increase_load", "hold", "insufficient_data")
        assert data["recovery_override"] is None

    async def test_golden_scenario_increase_load(self, async_client: AsyncClient):
        """Seed 3 bench press sessions at low RPE → expect increase_load."""
        for i in range(3):
            await async_client.post("/workouts", json={
                "date": str(TODAY - timedelta(days=2 - i)),
                "session_feeling_energy": 4,
                "sets": [
                    {"exercise_name": "barbell_bench_press", "set_number": 1, "reps": 8, "weight_kg": 100, "rpe": 7},
                ],
            })
        resp = await async_client.get(self.RECOMMEND_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "increase_load"
        assert data["recovery_override"] is None