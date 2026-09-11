import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from api.models.db import AgentAction, DeliveryJob, ExerciseTarget, FitnessGoal, HealthMetric, IngestBatch, LLMUsage, TelegramIdentity, TelegramUpdate, UserPreferences, UserProfile, WeightMeasurement, WorkerHeartbeat, WorkoutSession
from api.services import queue_service, workout_service
from api.services.llm_usage_service import reserve_attempt
from api.services.preferences_service import set_preference
from api.services.summary_service import progress_summary
from api.telegram.agent_actions import record_agent_action
from api.worker import process_one, deliver_one, tick

pytestmark = pytest.mark.asyncio
PATH = "/integrations/telegram/webhook"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret"}


def update(key, text=None, callback=None, user=1001):
    message = {"message_id": key, "chat": {"id": user, "type": "private"}, "from": {"id": user, "is_bot": False}, "text": text}
    if callback:
        return {"update_id": key, "callback_query": {"id": str(key), "from": message["from"], "message": message, "data": callback}}
    return {"update_id": key, "message": message}


async def receipt(client, key, text=None, callback=None, user=1001):
    # request() deliberately bypasses the fixture's automatic worker drain.
    return await client.request("POST", PATH, json=update(key, text, callback, user), headers=HEADERS)


async def user_id(db):
    return await db.scalar(select(TelegramIdentity.user_id).where(TelegramIdentity.telegram_user_id == 1001))


async def test_idle_worker_tick_updates_heartbeat_without_failing(db_session_factory):
    assert await tick(db_session_factory) is False
    async with db_session_factory() as db:
        heartbeat = await db.get(WorkerHeartbeat, "telegram")
        assert heartbeat is not None


async def test_receipt_is_durable_encrypted_and_deduplicated(async_client, db_session_factory, monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr("api.services.telegram_client.send_message", send)
    responses = await asyncio.gather(*(receipt(async_client, 1, "/log squat 3x5 at 100 kg") for _ in range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert sum(bool(r.json().get("duplicate")) for r in responses) == 1
    async with db_session_factory() as db:
        row = await db.get(TelegramUpdate, 1)
        assert row.status == "received" and "squat" not in row.encrypted_payload
        assert await db.scalar(select(func.count(AgentAction.id))) == 0
    send.assert_not_called()
    assert await process_one(db_session_factory)
    async with db_session_factory() as db:
        assert (await db.get(TelegramUpdate, 1)).encrypted_payload is None
        assert await db.scalar(select(func.count(DeliveryJob.id))) == 1
        assert await db.scalar(select(func.count(WorkoutSession.id))) == 0


async def test_concurrent_confirmation_writes_once(async_client, db_session_factory):
    await async_client.post(PATH, json=update(1, "/log squat 3x5 at 100 kg"), headers=HEADERS)
    async with db_session_factory() as db:
        action = await db.scalar(select(AgentAction).where(AgentAction.status == "pending_confirmation"))
        token = action.confirmation_token
    await asyncio.gather(receipt(async_client, 2, callback=f"confirm:{token}"), receipt(async_client, 3, callback=f"confirm:{token}"))
    await asyncio.gather(process_one(db_session_factory), process_one(db_session_factory))
    while await process_one(db_session_factory):
        pass
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count(WorkoutSession.id))) == 1
        assert (await db.get(AgentAction, action.id)).status == "completed"


async def test_delivery_failure_keeps_committed_weight_and_replay_is_safe(async_client, db_session_factory, monkeypatch):
    await async_client.post(PATH, json=update(1, "80 kg"), headers=HEADERS)
    async with db_session_factory() as db:
        action = await db.scalar(select(AgentAction).where(AgentAction.status == "pending_confirmation"))
    await receipt(async_client, 2, callback=f"confirm:{action.confirmation_token}")
    await process_one(db_session_factory)
    from api.services.telegram_client import TelegramDeliveryError
    failure = AsyncMock(side_effect=TelegramDeliveryError("rate_limited", retry_after=17))
    monkeypatch.setattr("api.services.telegram_client.answer_callback_query", failure)
    assert await deliver_one(db_session_factory)
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count(WeightMeasurement.id))) == 1
        retry = await db.scalar(select(DeliveryJob).where(DeliveryJob.status == "retry"))
        assert retry is not None
        assert retry.available_at > datetime.now(timezone.utc) + timedelta(seconds=10)
    assert (await receipt(async_client, 2, callback=f"confirm:{action.confirmation_token}")).json()["duplicate"]
    assert not await process_one(db_session_factory)


async def test_abandoned_lease_reclaims_and_stale_owner_cannot_finish(async_client, db_session_factory):
    await receipt(async_client, 1, "/start")
    async with db_session_factory() as db:
        job = await queue_service.claim(db, TelegramUpdate)
        stale = job.lease_token
        job.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    assert await process_one(db_session_factory)
    async with db_session_factory() as db:
        await queue_service.finish(db, TelegramUpdate, 1, stale, success=False)
        job = await db.get(TelegramUpdate, 1)
        assert job.status == "processed" and job.attempts == 2
        assert job.encrypted_payload is None


async def test_deleted_account_cannot_be_recreated_by_replay_or_old_button(async_client, db_session_factory):
    for key, text in [(1, "80 kg"), (2, "/delete"), (3, "DELETE")]:
        await async_client.post(PATH, json=update(key, text), headers=HEADERS)
    assert (await receipt(async_client, 1, "80 kg")).json()["duplicate"]
    await receipt(async_client, 4, callback="confirm:old-token")
    await process_one(db_session_factory)
    async with db_session_factory() as db:
        assert await user_id(db) is None
        rows = (await db.scalars(select(TelegramUpdate).where(TelegramUpdate.update_id.in_([1, 2, 3])))).all()
        assert all(r.telegram_user_id is None and r.encrypted_payload is None for r in rows)
        assert await db.scalar(select(func.count(AgentAction.id))) == 0


async def test_ai_consent_and_daily_budget_survive_workers(db_session_factory, monkeypatch):
    monkeypatch.setenv("LLM_DAILY_LIMIT_PER_USER", "2")
    async with db_session_factory() as db:
        uid = await user_id(db)
    assert not await reserve_attempt(db_session_factory, uid)
    async with db_session_factory() as db:
        await set_preference(db, uid, "ai", "on")
        db.add(LLMUsage(scope=str(uid), day=datetime.now(timezone.utc).date() - timedelta(days=1), attempts=500))
        await db.commit()
    results = await asyncio.gather(*(reserve_attempt(db_session_factory, uid) for _ in range(5)))
    assert sum(results) == 2
    async with db_session_factory() as db:
        await set_preference(db, uid, "ai", "off")
        await db.commit()
    assert not await reserve_attempt(db_session_factory, uid)


async def test_unconsented_text_never_calls_provider(async_client, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "1")
    provider = AsyncMock()
    monkeypatch.setattr("api.llm.gateway.interpret_free_text", provider)
    await async_client.post(PATH, json=update(1, "I trained squats today"), headers=HEADERS)
    provider.assert_not_called()


async def test_ingest_batch_conflict_and_validation_only(async_client, db_session_factory):
    data = {"batch_id": "morning-1", "hrv": 55}
    response = await async_client.post("/ingest/shortcut/validate", json=data)
    assert response.status_code == 200 and response.json()["valid"] == 1
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count(HealthMetric.id))) == 0
        assert await db.scalar(select(func.count(IngestBatch.batch_id))) == 0
    assert (await async_client.post("/ingest/shortcut", json=data)).json()["inserted"] == 1
    retry = await async_client.post("/ingest/shortcut", json=data)
    assert retry.json()["duplicates"] == 1 and retry.json()["batch_duplicate"]
    assert (await async_client.post("/ingest/shortcut", json={**data, "hrv": 60})).status_code == 409


async def test_correction_is_scoped_and_rejects_stale_revision(db_session_factory):
    async with db_session_factory() as db:
        uid = await user_id(db)
        other = UserProfile()
        db.add(other)
        await db.flush()
        sets = [{"exercise_name": "squat", "reps": 5, "weight_kg": 100, "rpe": None}]
        workout = await workout_service.create_workout(db, uid, date(2026, 8, 1), sets)
        with pytest.raises(ValueError):
            await workout_service.correct_workout(db, other.id, workout.id, 1, workout.date, sets)
        revised = await workout_service.correct_workout(db, uid, workout.id, 1, workout.date, [{**sets[0], "weight_kg": 105}])
        assert revised.revision == 2 and revised.sets[0].weight_kg == 105
        assert revised.sets[0].rpe is None
        with pytest.raises(ValueError):
            await workout_service.correct_workout(db, uid, workout.id, 1, workout.date, sets)
        audit = await db.scalar(select(AgentAction).where(AgentAction.action_type == "correct_workout"))
        assert audit is not None


async def test_weekly_goal_resets_and_exercise_filter_precedes_limit(db_session_factory, monkeypatch):
    today = date(2026, 9, 8)
    monkeypatch.setattr("api.services.summary_service.local_today", AsyncMock(return_value=today))
    async with db_session_factory() as db:
        uid = await user_id(db)
        db.add(FitnessGoal(user_id=uid, goal_type="frequency", target_value=3, unit="per_week", start_date=date(2026, 9, 1), status="active"))
        for day, exercise in [(1, "squat"), (2, "squat"), (6, "squat"), (7, "barbell_bench_press"), (8, "barbell_bench_press")]:
            await workout_service.create_workout(db, uid, date(2026, 9, day), [{"exercise_name": exercise, "reps": 5, "weight_kg": 80}])
        summary = await progress_summary(db, uid)
        assert summary["goals"][0]["current"] == 2
        assert [w["sessions"] for w in summary["weekly_sessions"]][-2:] == [3, 2]
        rows = await workout_service.exercise_history(db, uid, "squat", limit=2)
        assert len(rows) == 2


async def test_dashboard_error_headers_and_production_route_boundary(async_client, monkeypatch):
    invalid = await async_client.get("/dashboard?token=invalid")
    assert invalid.headers["cache-control"] == "no-store"
    assert invalid.headers["referrer-policy"] == "no-referrer"
    monkeypatch.setenv("FITKIT_PRODUCTION", "1")
    for path in ["/workouts", "/recommend/squat", "/health/summary", "/openapi.json", "/internal/metrics"]:
        assert (await async_client.get(path)).status_code == 404
    monkeypatch.setenv("FITKIT_BETA_USER_IDS", "999")
    assert (await receipt(async_client, 1, "/start")).json()["ignored"]


async def test_health_source_conflicts_and_sleep_totals_are_not_averaged(db_session_factory):
    from api.services.health_queries import get_recent_metric_readings
    from api.services.summary_service import health_snapshot
    today = date(2026, 9, 8)
    async with db_session_factory() as db:
        uid = await user_id(db)
        for kind, source, value, hour in [("hrv", "apple_watch", 40, 1), ("hrv", "apple_shortcuts", 80, 2),
                ("sleep_hours", "apple_shortcuts", 6, 1), ("sleep_hours", "apple_shortcuts", 8, 2)]:
            db.add(HealthMetric(user_id=uid, metric_type=kind, value=value, source=source, timestamp=datetime(2026, 9, 8, hour, tzinfo=timezone.utc)))
        await db.flush()
        assert await get_recent_metric_readings(db, uid, "hrv", 1, today) == [None]
        assert await get_recent_metric_readings(db, uid, "sleep_hours", 1, today) == [None]
        snapshot = await health_snapshot(db, uid, today)
        assert snapshot["freshness"]["hrv"]["conflicting_days"] == 1
        assert not snapshot["has_data"]


async def test_units_targets_and_missing_profile_support_existing_routine(async_client, db_session_factory):
    from api.services.target_service import set_target
    from api.services.recommendation_service import get_recommendation
    async with db_session_factory() as db:
        uid = await user_id(db)
        profile = await db.get(UserProfile, uid)
        assert profile.weight_kg is None and profile.age is None
        await set_preference(db, uid, "units", "lb")
        await set_target(db, uid, {"exercise_name": "squat", "target_reps": 5, "load_increment_kg": 2.5})
        for day in [1, 3, 6]:
            workout = await workout_service.create_workout(db, uid, date(2026, 9, day), [{"exercise_name": "squat", "reps": 5, "weight_kg": 100, "rpe": 7}])
            assert workout.session_feeling_energy is None
        result = await get_recommendation(db, uid, "squat", today=date(2026, 9, 8))
        assert result.decision.value == "increase_load"
        assert result.suggested_load_kg == 102.5
        other = UserProfile()
        db.add(other)
        await db.flush()
        isolated = await get_recommendation(db, other.id, "squat", today=date(2026, 9, 8))
        assert isolated.decision.value == "insufficient_data"
        assert "target_reps" in isolated.missing_inputs


async def test_unhandled_failures_do_not_log_user_values(async_client, monkeypatch, caplog):
    monkeypatch.setattr("api.routers.health.health_snapshot", AsyncMock(side_effect=RuntimeError("synthetic-health-payload")))
    response = await async_client.get("/health/summary")
    assert response.status_code == 500
    assert "synthetic-health-payload" not in response.text
    assert "synthetic-health-payload" not in caplog.text


async def test_repeated_worker_crashes_exhaust_attempts(async_client, db_session_factory):
    await receipt(async_client, 1, "/start")
    async with db_session_factory() as db:
        row = await db.get(TelegramUpdate, 1)
        row.status, row.attempts = "processing", 4
        row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    assert not await process_one(db_session_factory)
    async with db_session_factory() as db:
        row = await db.get(TelegramUpdate, 1)
        assert row.status == "failed" and row.error_code == "lease_attempts_exhausted"
    await receipt(async_client, 2, "/help")
    assert await process_one(db_session_factory)


async def test_concurrent_deletion_cannot_leave_ai_usage(db_session_factory):
    from api.services.user_data import delete_user_data
    async with db_session_factory() as db:
        uid = await user_id(db)
        await set_preference(db, uid, "ai", "on")
        await db.commit()
    async def delete_account():
        async with db_session_factory() as db:
            await delete_user_data(db, uid)
            await db.commit()
    await asyncio.gather(reserve_attempt(db_session_factory, uid), delete_account(), reserve_attempt(db_session_factory, uid))
    async with db_session_factory() as db:
        assert await db.get(UserProfile, uid) is None
        assert await db.scalar(select(func.count()).select_from(LLMUsage).where(LLMUsage.scope == str(uid))) == 0
