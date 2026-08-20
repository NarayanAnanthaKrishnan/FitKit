"""Explicitly bootstrap a legacy FitKit database and stamp Alembic head.

This command is intentionally separate from application startup. It creates
missing current-model tables, applies only the known onboarding nullability
compatibility changes, compares the complete SQLAlchemy metadata contract, and
records the Alembic baseline in the same transaction. Make a backup and review
the output before using it against any shared or production database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    inspect,
    text,
)
from sqlalchemy.ext.asyncio import create_async_engine

from api.models.db import Base

_SCRIPT_LOCATION = str(Path(__file__).resolve().parent.parent / "alembic")


def _head_revision() -> str:
    """Resolve the current Alembic head from the migration scripts."""
    return ScriptDirectory(_SCRIPT_LOCATION).get_current_head()


def _validate_schema(connection) -> None:
    migration_context = MigrationContext.configure(connection)
    differences = compare_metadata(migration_context, Base.metadata)
    if differences:
        raise RuntimeError(
            "Legacy schema differs from the current SQLAlchemy metadata; "
            "review a dedicated migration instead of stamping: "
            f"{differences!r}"
        )


def _alembic_version_exists(connection) -> bool:
    return inspect(connection).has_table("alembic_version")


def _stamp_head(connection, head: str) -> None:
    metadata = MetaData()
    version_table = Table(
        "alembic_version",
        metadata,
        Column("version_num", String(length=32), nullable=False),
        PrimaryKeyConstraint("version_num", name="alembic_version_pkc"),
    )
    metadata.create_all(connection)
    connection.execute(version_table.insert().values(version_num=head))


async def bootstrap(database_url: str) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        if await connection.run_sync(_alembic_version_exists):
            raise RuntimeError(
                "alembic_version already exists; use Alembic directly instead of "
                "the legacy bootstrap command."
            )

        await connection.run_sync(Base.metadata.create_all)
        for column in ("weight_kg", "age", "sex", "resting_hr"):
            await connection.execute(
                text(
                    f"ALTER TABLE user_profiles ALTER COLUMN {column} DROP NOT NULL"
                )
            )
        await connection.run_sync(_validate_schema)
        await connection.run_sync(_stamp_head, _head_revision())
    await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate/bootstrap a legacy database and stamp Alembic head."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the explicit bootstrap and stamp Alembic head.",
    )
    args = parser.parse_args()
    if not args.apply:
        parser.error("refusing to change a database without --apply")

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required; configure .env first")

    try:
        asyncio.run(bootstrap(database_url))
    except (OSError, RuntimeError) as exc:
        print(f"Legacy database bootstrap failed: {exc}")
        return 1
    print("Legacy database validated and stamped at Alembic head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
