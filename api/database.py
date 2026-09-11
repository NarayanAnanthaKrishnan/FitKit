import csv
import os
from collections.abc import AsyncGenerator
from importlib.resources import files

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

load_dotenv()

from api.config import settings
DATABASE_URL = settings.database_url
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is required. Copy .env.example to .env and configure it."
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


async def seed_exercise_taxonomy(db: AsyncSession):
    from api.models.db import ExerciseTaxonomy
    from sqlalchemy.dialects.postgresql import insert
    csv_path = files("api").joinpath("data/exercise_taxonomy.csv")
    if not csv_path.is_file():
        raise RuntimeError("Packaged exercise taxonomy is missing")
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError("Packaged exercise taxonomy is empty")
    stmt = insert(ExerciseTaxonomy).values(rows)
    await db.execute(stmt.on_conflict_do_update(index_elements=["name"], set_={key: getattr(stmt.excluded, key) for key in ("display_name", "muscle_group", "equipment")}))
    await db.commit()
