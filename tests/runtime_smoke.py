"""Run inside the built image against an isolated *_migrations database.

Example: docker run -i ... fitkit:local python - < tests/runtime_smoke.py
No test framework is installed in the production image; external transport is
stubbed. The test exercises application lifespan, receipts, worker and routes.
"""
import asyncio
import os
import time
from urllib.parse import urlsplit

assert urlsplit(os.environ["DATABASE_URL"]).path.endswith("_migrations")
from importlib.resources import files
assert files("api").joinpath("data/exercise_taxonomy.csv").is_file()
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from api.main import app, lifespan
from api.database import async_session_factory
from api.models.db import AgentAction, TelegramIdentity, WorkoutSession
from api.services import telegram_client
from api.worker import tick


async def main():
    key_base = time.time_ns() // 1000
    sent = []
    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)
    async def fake_answer(callback_query_id, text=None):
        pass
    telegram_client.send_message = fake_send
    telegram_client.answer_callback_query = fake_answer
    async with lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://smoke") as client:
            async def message(key, text):
                response = await client.post("/integrations/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": os.environ["TELEGRAM_WEBHOOK_SECRET"]},
                    json={"update_id": key_base + key, "message": {"from": {"id": 987654}, "chat": {"id": 987654, "type": "private"}, "text": text}})
                assert response.status_code == 200
                await tick()
            assert (await client.get("/health")).status_code == 200
            await message(987654001, "/start")
            async with async_session_factory() as db:
                uid = await db.scalar(select(TelegramIdentity.user_id).where(TelegramIdentity.telegram_user_id == 987654))
                before_count = await db.scalar(select(func.count()).select_from(WorkoutSession).where(WorkoutSession.user_id == uid))
            await message(987654002, "/log squat 3x5 at 100 kg rpe 7")
            async with async_session_factory() as db:
                uid = await db.scalar(select(TelegramIdentity.user_id).where(TelegramIdentity.telegram_user_id == 987654))
                action = await db.scalar(select(AgentAction).where(AgentAction.user_id == uid, AgentAction.status == "pending_confirmation"))
                assert action.action_type == "log_workout"
                assert await db.scalar(select(func.count()).select_from(WorkoutSession).where(WorkoutSession.user_id == uid)) == before_count
            await message(987654003, "save")
            async with async_session_factory() as db:
                assert await db.scalar(select(func.count()).select_from(WorkoutSession).where(WorkoutSession.user_id == uid)) == before_count + 1
            assert (await client.get("/ready")).status_code == 200
            assert (await client.get("/workouts")).status_code == 404
            assert (await client.get("/dashboard?token=invalid")).headers["cache-control"] == "no-store"
            assert any("Workout saved" in text for text in sent)
    print("Container smoke passed: package, lifespan, queued receipt, confirmed workout, delivery, readiness, private routes.")


asyncio.run(main())
