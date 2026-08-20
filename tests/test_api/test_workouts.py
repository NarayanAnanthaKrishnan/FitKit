import uuid

import pytest
from httpx import AsyncClient

from api.models.db import TelegramIdentity, UserProfile

pytestmark = pytest.mark.asyncio


class TestCreateWorkout:
    CREATE_URL = "/workouts"

    @pytest.fixture
    def valid_payload(self):
        return {
            "date": "2026-07-25",
            "session_feeling_energy": 4,
            "session_feeling_soreness": ["chest", "triceps"],
            "sets": [
                {
                    "exercise_name": "barbell_bench_press",
                    "set_number": 1,
                    "reps": 8,
                    "weight_kg": 100.0,
                    "rpe": 7,
                },
                {
                    "exercise_name": "barbell_bench_press",
                    "set_number": 2,
                    "reps": 8,
                    "weight_kg": 100.0,
                    "rpe": 8,
                },
            ],
        }

    async def test_create_workout_success(self, async_client: AsyncClient, valid_payload):
        resp = await async_client.post(self.CREATE_URL, json=valid_payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["date"] == "2026-07-25"
        assert len(data["sets"]) == 2
        assert data["sets"][0]["exercise_name"] == "barbell_bench_press"
        assert data["session_feeling_energy"] == 4

    async def test_create_workout_with_mood(self, async_client: AsyncClient, valid_payload):
        valid_payload["session_feeling_mood"] = "felt strong today"
        resp = await async_client.post(self.CREATE_URL, json=valid_payload)
        assert resp.status_code == 201
        assert resp.json()["session_feeling_mood"] == "felt strong today"

    async def test_create_workout_unknown_exercise(self, async_client: AsyncClient, valid_payload):
        valid_payload["sets"][0]["exercise_name"] = "nonexistent_lift"
        resp = await async_client.post(self.CREATE_URL, json=valid_payload)
        assert resp.status_code == 422
        assert "nonexistent_lift" in resp.text

    async def test_create_workout_missing_rpe(self, async_client: AsyncClient, valid_payload):
        del valid_payload["sets"][0]["rpe"]
        resp = await async_client.post(self.CREATE_URL, json=valid_payload)
        assert resp.status_code == 201
        assert resp.json()["sets"][0]["rpe"] is None

    async def test_create_workout_empty_sets(self, async_client: AsyncClient, valid_payload):
        valid_payload["sets"] = []
        resp = await async_client.post(self.CREATE_URL, json=valid_payload)
        assert resp.status_code == 422


class TestGetWorkout:
    async def test_get_workout_by_id(self, async_client: AsyncClient):
        payload = {
            "date": "2026-07-25",
            "session_feeling_energy": 3,
            "sets": [
                {"exercise_name": "squat", "set_number": 1, "reps": 5, "weight_kg": 140, "rpe": 8},
            ],
        }
        create_resp = await async_client.post("/workouts", json=payload)
        assert create_resp.status_code == 201
        workout_id = create_resp.json()["id"]

        resp = await async_client.get(f"/workouts/{workout_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == workout_id
        assert resp.json()["sets"][0]["exercise_name"] == "squat"

    async def test_get_workout_not_found(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/workouts/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404

    async def test_get_workout_invalid_uuid(self, async_client: AsyncClient):
        resp = await async_client.get("/workouts/not-a-uuid")
        assert resp.status_code == 422


class TestExerciseHistory:
    async def test_empty_history(self, async_client: AsyncClient):
        resp = await async_client.get("/workouts/goblet_squat/history")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_history_returns_recent_sessions(self, async_client: AsyncClient):
        for i in range(3):
            payload = {
                "date": f"2026-07-{23 + i:02d}",
                "session_feeling_energy": 4,
                "sets": [
                    {
                        "exercise_name": "overhead_press",
                        "set_number": 1,
                        "reps": 8,
                        "weight_kg": 100,
                        "rpe": 7,
                    },
                ],
            }
            await async_client.post("/workouts", json=payload)

        resp = await async_client.get("/workouts/overhead_press/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        assert data[0]["session_date"] >= data[-1]["session_date"]

    async def test_history_filters_by_exercise(self, async_client: AsyncClient):
        await async_client.post("/workouts", json={
            "date": "2026-07-25",
            "session_feeling_energy": 3,
            "sets": [
                {"exercise_name": "squat", "set_number": 1, "reps": 5, "weight_kg": 140, "rpe": 8},
            ],
        })
        await async_client.post("/workouts", json={
            "date": "2026-07-25",
            "session_feeling_energy": 4,
            "sets": [
                {"exercise_name": "deadlift", "set_number": 1, "reps": 5, "weight_kg": 180, "rpe": 8},
            ],
        })

        resp = await async_client.get("/workouts/deadlift/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_history_unknown_exercise(self, async_client: AsyncClient):
        resp = await async_client.get("/workouts/nonexistent_lift/history")
        assert resp.status_code == 404

    async def test_unknown_telegram_identity_is_rejected(
        self, async_client: AsyncClient
    ):
        resp = await async_client.get(
            "/workouts/squat/history",
            headers={"X-Telegram-User-Id": "999999"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Telegram user is not linked"

    async def test_workout_isolation_between_linked_telegram_users(
        self, async_client: AsyncClient, db_session
    ):
        other_user = UserProfile()
        db_session.add(other_user)
        await db_session.flush()
        db_session.add(
            TelegramIdentity(
                user_id=other_user.id,
                telegram_user_id=2002,
                telegram_chat_id=2002,
                onboarding_step="complete",
            )
        )
        await db_session.commit()

        create_resp = await async_client.post(
            "/workouts",
            json={
                "date": "2026-07-25",
                "session_feeling_energy": 4,
                "sets": [
                    {
                        "exercise_name": "squat",
                        "set_number": 1,
                        "reps": 5,
                        "weight_kg": 140,
                        "rpe": 8,
                    }
                ],
            },
        )
        assert create_resp.status_code == 201
        workout_id = create_resp.json()["id"]

        other_view = await async_client.get(
            f"/workouts/{workout_id}",
            headers={"X-Telegram-User-Id": "2002"},
        )
        assert other_view.status_code == 404
