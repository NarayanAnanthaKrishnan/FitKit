import csv
import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from api.models.db import Base, ExerciseTaxonomy

os.environ.setdefault("FITKIT_API_KEY", "test-api-key")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-telegram-secret")

TEST_DB_URL = "postgresql+asyncpg://postgres:fitkit@localhost:5432/fitkit_test"

test_engine = create_async_engine(
    TEST_DB_URL, echo=False, poolclass=NullPool
)
TestSessionFactory = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="session")
async def _tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE user_profiles ALTER COLUMN weight_kg DROP NOT NULL")
        )
        await conn.execute(
            text("ALTER TABLE user_profiles ALTER COLUMN age DROP NOT NULL")
        )
        await conn.execute(
            text("ALTER TABLE user_profiles ALTER COLUMN sex DROP NOT NULL")
        )
        await conn.execute(
            text("ALTER TABLE user_profiles ALTER COLUMN resting_hr DROP NOT NULL")
        )
    yield


@pytest_asyncio.fixture(scope="session")
async def _clean_db(_tables):
    tables_to_truncate = [
        "telegram_updates",
        "telegram_identities",
        "weight_measurements",
        "exercise_sets",
        "workout_sessions",
        "health_metrics",
        "user_profiles",
    ]
    async with TestSessionFactory() as session:
        for table in tables_to_truncate:
            await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        await session.commit()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _seed_taxonomy(_clean_db):
    csv_path = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "exercise_taxonomy.csv"
    )
    if not csv_path.exists():
        return
    async with TestSessionFactory() as session:
        count = await session.scalar(select(func.count(ExerciseTaxonomy.name)))
        if count and count > 0:
            return
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                session.add(
                    ExerciseTaxonomy(
                        name=row["name"],
                        display_name=row["display_name"],
                        muscle_group=row["muscle_group"],
                        equipment=row["equipment"],
                    )
                )
        await session.commit()


@pytest_asyncio.fixture
async def db_session_factory():
    return TestSessionFactory


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionFactory() as session:
        yield session


@pytest_asyncio.fixture
async def async_client():
    from httpx import ASGITransport, AsyncClient

    from api.main import app
    from api.database import get_db

    async def override_get_db():
        async with TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
