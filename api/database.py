import csv
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:fitkit@localhost:5432/fitkit",
)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    from api.models.db import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # `create_all` does not alter existing columns. These statements make
        # pre-Telegram databases compatible with resumable onboarding.
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


async def seed_exercise_taxonomy(db: AsyncSession):
    from api.models.db import ExerciseTaxonomy

    count = await db.scalar(select(func.count(ExerciseTaxonomy.name)))
    if count and count > 0:
        return

    csv_path = (
        Path(__file__).resolve().parent.parent / "docs" / "exercise_taxonomy.csv"
    )
    if not csv_path.exists():
        return

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db.add(
                ExerciseTaxonomy(
                    name=row["name"],
                    display_name=row["display_name"],
                    muscle_group=row["muscle_group"],
                    equipment=row["equipment"],
                )
            )
    await db.commit()
