from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.database import async_session_factory, init_db, seed_exercise_taxonomy
from api.routers import health, ingest, recommend, telegram, workouts


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    async with async_session_factory() as session:
        await seed_exercise_taxonomy(session)
    yield


app = FastAPI(title="FitKit", version="0.1.0", lifespan=lifespan)
app.include_router(workouts.router)
app.include_router(recommend.router)
app.include_router(ingest.router)
app.include_router(health.router)
app.include_router(telegram.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
