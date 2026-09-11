import secrets

from api.config import settings


def telegram_secret_matches(received: str | None) -> bool:
    expected = settings.telegram_webhook_secret
    if not expected or not received:
        return False
    return secrets.compare_digest(
        received.encode("utf-8"), expected.encode("utf-8")
    )
