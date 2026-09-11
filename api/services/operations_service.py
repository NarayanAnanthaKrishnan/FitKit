from datetime import datetime, timezone
from sqlalchemy import func, select
from api.models.db import AgentAction, DeliveryJob, FeedbackSample, InteractionEvent, LLMUsage, TelegramUpdate


async def queue_metrics(db):
    result = {}
    for label, model, timestamp in (("inbound", TelegramUpdate, TelegramUpdate.received_at), ("outbound", DeliveryJob, DeliveryJob.created_at)):
        counts = (await db.execute(select(model.status, func.count()).group_by(model.status))).all()
        oldest = await db.scalar(select(func.min(timestamp)).where(model.status.in_(("received", "pending", "processing", "retry"))))
        result[label] = {"counts": dict(counts), "oldest_pending_seconds": max(0, (datetime.now(timezone.utc) - oldest).total_seconds()) if oldest else 0}
    result["actions"] = dict((await db.execute(select(AgentAction.status, func.count()).group_by(AgentAction.status))).all())
    result["action_types"] = dict((await db.execute(select(AgentAction.action_type, func.count()).group_by(AgentAction.action_type))).all())
    result["llm_attempts_today"] = await db.scalar(select(LLMUsage.attempts).where(LLMUsage.scope == "global", LLMUsage.day == datetime.now(timezone.utc).date())) or 0
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    route_counts = (await db.execute(select(InteractionEvent.route, func.count()).where(
        InteractionEvent.created_at >= since
    ).group_by(InteractionEvent.route))).all()
    outcome_counts = (await db.execute(select(InteractionEvent.outcome, func.count()).where(
        InteractionEvent.created_at >= since
    ).group_by(InteractionEvent.outcome))).all()
    rating_counts = (await db.execute(select(InteractionEvent.rating, func.count()).where(
        InteractionEvent.created_at >= since, InteractionEvent.rating.is_not(None)
    ).group_by(InteractionEvent.rating))).all()
    result["conversation_today"] = {
        "routes": dict(route_counts),
        "outcomes": dict(outcome_counts),
        "ratings": dict(rating_counts),
        "feedback_samples": await db.scalar(select(func.count(FeedbackSample.id)).where(
            FeedbackSample.expires_at > datetime.now(timezone.utc)
        )) or 0,
    }
    task_outcomes = (await db.execute(select(
        InteractionEvent.outcome, func.count()
    ).where(
        InteractionEvent.created_at >= since,
        InteractionEvent.task_id.is_not(None),
    ).group_by(InteractionEvent.outcome))).all()
    task_stages = (await db.execute(select(
        InteractionEvent.task_stage, func.count()
    ).where(
        InteractionEvent.created_at >= since,
        InteractionEvent.task_id.is_not(None),
        InteractionEvent.task_stage.is_not(None),
    ).group_by(InteractionEvent.task_stage))).all()
    latencies = list((await db.scalars(select(InteractionEvent.latency_ms).where(
        InteractionEvent.created_at >= since,
        InteractionEvent.route == "llm",
        InteractionEvent.latency_ms.is_not(None),
    ).order_by(InteractionEvent.latency_ms))).all())

    def percentile(values, fraction):
        if not values:
            return None
        return values[min(len(values) - 1, max(0, round((len(values) - 1) * fraction)))]

    result["conversation_today"]["task_outcomes"] = dict(task_outcomes)
    result["conversation_today"]["task_stages"] = dict(task_stages)
    result["conversation_today"]["llm_latency_ms"] = {
        "count": len(latencies),
        "p50": percentile(latencies, 0.5),
        "p95": percentile(latencies, 0.95),
    }
    return result
