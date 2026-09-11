"""Compatibility import for the established public router path."""
from api.telegram.router import router, telegram_webhook

__all__ = ["router", "telegram_webhook"]
