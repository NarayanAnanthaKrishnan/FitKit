"""Migration-backed, per-test isolated PostgreSQL fixtures; all providers are mocked."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:fitkit@127.0.0.1:5432/fitkit_beta_test")
if not urlsplit(TEST_DB_URL).path.endswith("_test"):
    raise RuntimeError("Integration tests require a dedicated database ending in _test")
os.environ.update({"DATABASE_URL": TEST_DB_URL, "FITKIT_API_KEY": "test-api-key", "TELEGRAM_WEBHOOK_SECRET": "test-telegram-secret",
    "TELEGRAM_BOT_TOKEN": "test-token", "ALLOW_LEGACY_INGEST_AUTH": "1", "LLM_ENABLED": "0", "FITKIT_PRODUCTION": "0",
    "TELEGRAM_CONVERSATION_V2": "0", "FITKIT_BETA_USER_IDS": "",
    "FITKIT_QUEUE_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "FITKIT_MEMORY_KEY": "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="})

from api.models.db import Base, TelegramIdentity, UserProfile
from api.database import seed_exercise_taxonomy

REST_TELEGRAM_USER_ID = 1001
test_engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
TestSessionFactory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def _tables():
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")


@pytest_asyncio.fixture(scope="session")
async def _seed_taxonomy(_tables):
    async with TestSessionFactory() as db:
        await seed_exercise_taxonomy(db)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db(_seed_taxonomy, monkeypatch):
    tables = [f'"{table.name}"' for table in Base.metadata.sorted_tables if table.name != "exercise_taxonomy"]
    async with TestSessionFactory() as db:
        await db.execute(text("TRUNCATE TABLE " + ", ".join(tables) + " CASCADE"))
        user = UserProfile()
        db.add(user)
        await db.flush()
        db.add(TelegramIdentity(user_id=user.id, telegram_user_id=REST_TELEGRAM_USER_ID,
            telegram_chat_id=REST_TELEGRAM_USER_ID, onboarding_step="complete"))
        await db.commit()
    async def no_send(*args, **kwargs):
        return None
    monkeypatch.setattr("api.services.telegram_client.send_message", no_send)
    monkeypatch.setattr("api.services.telegram_client.answer_callback_query", no_send)
    monkeypatch.setenv("LLM_ENABLED", "0")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")


@pytest_asyncio.fixture
async def db_session_factory():
    return TestSessionFactory


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionFactory() as db:
        yield db


@pytest_asyncio.fixture
async def async_client():
    from httpx import ASGITransport, AsyncClient
    from api.main import app
    from api.database import get_db
    from api.worker import process_one, deliver_one

    async def override_get_db():
        async with TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    class WorkerClient(AsyncClient):
        async def post(self, url, **kwargs):
            response = await super().post(url, **kwargs)
            if str(url).endswith("/integrations/telegram/webhook"):
                for _ in range(100):
                    if not await process_one(TestSessionFactory):
                        break
                for _ in range(200):
                    if not await deliver_one(TestSessionFactory):
                        break
            return response

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with WorkerClient(transport=ASGITransport(app=app), base_url="http://test",
            headers={"X-API-Key": "test-api-key", "X-Telegram-User-Id": str(REST_TELEGRAM_USER_ID)}) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
