"""Local operator commands; outputs contain aggregate metrics, never payloads."""
import argparse
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from api.database import async_session_factory
from api.models.db import DeliveryJob, TelegramUpdate
from api.services.operations_service import queue_metrics


async def run(args):
    async with async_session_factory() as db:
        if args.command == "metrics":
            print(json.dumps(await queue_metrics(db), indent=2))
            return
        model = TelegramUpdate if args.queue == "inbound" else DeliveryJob
        key = int(args.id) if model is TelegramUpdate else uuid.UUID(args.id)
        row = await db.get(model, key, with_for_update=True)
        created = row.received_at if row and model is TelegramUpdate else (row.created_at if row else None)
        if row is None or row.status != "failed" or not row.encrypted_payload or created < datetime.now(timezone.utc) - timedelta(hours=24):
            raise ValueError("Only failed jobs with unexpired payloads can be retried")
        row.status, row.attempts = "retry", 0
        row.available_at = datetime.now(timezone.utc)
        row.lease_token = row.lease_until = row.error_code = None
        await db.commit()
        print("Job queued for retry. Outbound retries may repeat an already delivered message.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("metrics")
    retry = commands.add_parser("retry")
    retry.add_argument("queue", choices=["inbound", "outbound"])
    retry.add_argument("id")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        # Database exceptions can contain connection information or SQL values.
        parser.exit(1, f"Operation failed ({type(exc).__name__}); check configuration and job eligibility.\n")


if __name__ == "__main__":
    main()
