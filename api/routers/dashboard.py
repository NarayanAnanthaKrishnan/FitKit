"""Private insights dashboard.

The dashboard is reachable only through an opaque, short-lived, user-scoped
token generated in Telegram. It renders the same summary data the Telegram
commands expose, so it is a view over domain services rather than a separate
data path.
"""

import html

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.services.dashboard_service import resolve_user_by_token
from api.services.summary_service import health_snapshot, progress_summary, today_snapshot

router = APIRouter(tags=["dashboard"])

_CSS = """
body { font-family: -apple-system, system-ui, sans-serif; max-width: 640px;
       margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
h1 { font-size: 1.5rem; }
section { border-top: 1px solid #e5e5e5; padding: 0.75rem 0; }
h2 { font-size: 1rem; margin: 0 0 0.5rem; color: #555; }
.row { display: flex; justify-content: space-between; padding: 0.2rem 0; }
.muted { color: #777; }
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(token: str, db: AsyncSession = Depends(get_db)):
    user = await resolve_user_by_token(db, token)
    if user is None:
        raise HTTPException(
            status_code=401, detail="Invalid or expired dashboard link"
        )

    snapshot = await today_snapshot(db, user.id)
    progress = await progress_summary(db, user.id)
    health = await health_snapshot(db, user.id)

    return HTMLResponse(
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>FitKit</title><style>{_CSS}</style></head><body>"
            "<h1>FitKit</h1>"
            + _weight_section(progress["weight"])
            + _goals_section(progress["goals"])
            + _health_section(health)
            + _workout_section(snapshot.get("last_workout"))
            + _footer()
            + "</body></html>"
        )
    )


def _weight_section(weight: dict) -> str:
    latest = weight.get("latest_kg")
    if latest is None:
        body = "<div class='muted'>No weight measurements yet.</div>"
    else:
        row = f"<div class='row'><span>Latest</span><span>{latest:.1f} kg</span></div>"
        if weight.get("change_7d") is not None:
            row += (
                f"<div class='row'><span>7-day change</span>"
                f"<span>{weight['change_7d']:+.1f} kg</span></div>"
            )
        if weight.get("change_30d") is not None:
            row += (
                f"<div class='row'><span>30-day change</span>"
                f"<span>{weight['change_30d']:+.1f} kg</span></div>"
            )
        body = row
    return f"<section><h2>Weight</h2>{body}</section>"


def _goals_section(goals: list[dict]) -> str:
    if not goals:
        body = "<div class='muted'>No active goals.</div>"
    else:
        rows = []
        for goal in goals:
            ref = html.escape(str(goal["ref"]))
            if goal["type"] == "frequency":
                label = (
                    f"{goal['current']}/{goal['target']:.0f} "
                    f"{html.escape(str(goal['unit']))} "
                    f"({goal['progress_pct']}%)"
                )
            else:
                current = (
                    f"{goal['current']:.1f}" if goal["current"] is not None else "?"
                )
                label = (
                    f"{current} / {goal['target']} "
                    f"{html.escape(str(goal['unit']))}"
                )
            rows.append(f"<div class='row'><span>{ref}</span><span>{label}</span></div>")
        body = "".join(rows)
    return f"<section><h2>Goals</h2>{body}</section>"


def _health_section(health: dict) -> str:
    if not health.get("has_data"):
        body = "<div class='muted'>No health data connected yet.</div>"
    else:
        rows = []
        if health.get("latest_hrv") is not None:
            rows.append(
                f"<div class='row'><span>Latest HRV</span>"
                f"<span>{health['latest_hrv']} ms</span></div>"
            )
        if health.get("latest_sleep_hours") is not None:
            rows.append(
                f"<div class='row'><span>Latest sleep</span>"
                f"<span>{health['latest_sleep_hours']} h</span></div>"
            )
        if health.get("latest_resting_hr") is not None:
            rows.append(
                f"<div class='row'><span>Resting HR</span>"
                f"<span>{health['latest_resting_hr']} bpm</span></div>"
            )
        if health.get("hrv_baseline_7day") is not None:
            rows.append(
                f"<div class='row'><span>HRV baseline (7d)</span>"
                f"<span>{health['hrv_baseline_7day']} ms</span></div>"
            )
        body = "".join(rows)
    return f"<section><h2>Recovery</h2>{body}</section>"


def _workout_section(last_workout: dict | None) -> str:
    if last_workout is None:
        body = "<div class='muted'>No workouts logged yet.</div>"
    else:
        exercises = ", ".join(last_workout["exercises"]) or "no exercises"
        body = (
            f"<div class='row'><span>Date</span><span>{last_workout['date']}</span></div>"
            f"<div class='row'><span>Exercises</span><span>{html.escape(exercises)}</span></div>"
        )
    return f"<section><h2>Last workout</h2>{body}</section>"


def _footer() -> str:
    return (
        "<section class='muted'>This link is private, temporary, and tied to your "
        "FitKit account. Do not share it.</section>"
    )
