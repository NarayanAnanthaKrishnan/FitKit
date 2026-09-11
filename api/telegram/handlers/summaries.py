from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models.db import UserProfile
from api.services.dashboard_service import create_link as create_dashboard_link
from api.services.health_pairing_service import create_pairing
from api.services.summary_service import health_snapshot, progress_summary, today_snapshot
from api.telegram.client import send_telegram_message
from api.telegram.formatting import format_health, format_progress, format_today


async def handle_today(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    snapshot = await today_snapshot(db, user.id)
    await send_telegram_message(chat_id, format_today(snapshot))


async def handle_progress(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    summary = await progress_summary(db, user.id)
    await send_telegram_message(chat_id, format_progress(summary))


async def handle_health(db: AsyncSession, user: UserProfile, chat_id: int) -> None:
    health = await health_snapshot(db, user.id)
    await send_telegram_message(chat_id, format_health(health))


async def handle_connect_health(
    db: AsyncSession, user: UserProfile, chat_id: int
) -> None:
    token, _ = await create_pairing(db, user.id)
    base_url = settings.public_base_url
    health_endpoint = (
        f"{base_url}/ingest/health"
        if base_url
        else "https://<your-deployed-host>/ingest/health"
    )
    shortcut_endpoint = (
        f"{base_url}/ingest/shortcut"
        if base_url
        else "https://<your-deployed-host>/ingest/shortcut"
    )
    await send_telegram_message(
        chat_id,
        "Connect health data to your FitKit account:\n\n"
        "Health Auto Export (third-party app):\n"
        f"  Endpoint: {health_endpoint}\n"
        "Apple Shortcuts (no app, no third party):\n"
        f"  Endpoint: {shortcut_endpoint}\n\n"
        "Use this header for both:\n"
        f"X-Health-Pairing-Token: {token}\n\n"
        "Keep this token private — anyone with it can write to your health data. "
        "Send /connect-health again to rotate it.",
    )


async def handle_dashboard(
    db: AsyncSession, user: UserProfile, chat_id: int
) -> None:
    token, _ = await create_dashboard_link(db, user.id)
    base_url = settings.public_base_url
    if not base_url:
        await send_telegram_message(
            chat_id,
            "Dashboard links need a PUBLIC_BASE_URL to be configured. "
            "Ask the operator to set it, then try /dashboard again.",
        )
        return
    url = f"{base_url}/dashboard?token={token}"
    await send_telegram_message(
        chat_id,
        f"Your private dashboard is ready (expires soon):\n{url}\n\n"
        "Do not share this link.",
    )
