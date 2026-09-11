from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.database import async_session_factory, seed_exercise_taxonomy
from api.routers import dashboard, health, ingest, recommend, telegram, workouts
from api.config import settings
from api.security import BoundaryMiddleware, configure_logging
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings.validate()
    # Database schema changes are applied explicitly with Alembic before the
    # application starts. Startup may seed the static exercise vocabulary, but
    # it must never create or alter tables implicitly.
    async with async_session_factory() as session:
        await seed_exercise_taxonomy(session)
    yield


app = FastAPI(title="FitKit", version="0.1.0", lifespan=lifespan)
app.add_middleware(BoundaryMiddleware)
from api.services.ingestion_service import BatchConflict
from fastapi.responses import JSONResponse


@app.exception_handler(BatchConflict)
async def batch_conflict_handler(request, exc):
    return JSONResponse({"detail": "Batch ID was already used for different data"}, status_code=409)

app.include_router(workouts.router)
app.include_router(recommend.router)
app.include_router(ingest.router)
app.include_router(health.router)
app.include_router(telegram.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, text, func
    from fastapi.responses import JSONResponse
    from api.models.db import ExerciseTaxonomy, WorkerHeartbeat
    try:
        async with async_session_factory() as db:
            version = await db.scalar(text("SELECT version_num FROM alembic_version"))
            taxonomy_count = await db.scalar(select(func.count(ExerciseTaxonomy.name)))
            heartbeat = await db.get(WorkerHeartbeat, "telegram")
            ok = version == "20260911_0014" and taxonomy_count > 0 and heartbeat is not None and heartbeat.seen_at > datetime.now(timezone.utc) - timedelta(seconds=90)
    except Exception:
        ok = False
    return JSONResponse({"status": "ready" if ok else "not_ready"}, status_code=200 if ok else 503)


@app.get("/internal/metrics")
async def metrics():
    from api.services.operations_service import queue_metrics
    async with async_session_factory() as db:
        return await queue_metrics(db)
