"""Validated environment settings; reloadable properties support isolated tests."""
import math
import os
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


def integer(name: str, default: int, minimum: int = 1, maximum: int = 1_000_000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise RuntimeError(f"Invalid {name}") from None
    if not minimum <= value <= maximum:
        raise RuntimeError(f"Invalid {name}")
    return value


def boolean(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default)
    if value not in {"0", "1"}:
        raise RuntimeError(f"Invalid {name}; use 0 or 1")
    return value == "1"


class Settings:
    database_url = property(lambda self: os.getenv("DATABASE_URL"))
    fitkit_api_key = property(lambda self: os.getenv("FITKIT_API_KEY"))
    telegram_bot_token = property(lambda self: os.getenv("TELEGRAM_BOT_TOKEN"))
    telegram_webhook_secret = property(lambda self: os.getenv("TELEGRAM_WEBHOOK_SECRET"))
    public_base_url = property(lambda self: os.getenv("PUBLIC_BASE_URL", "").rstrip("/"))
    groq_api_key = property(lambda self: os.getenv("GROQ_API_KEY"))
    groq_model = property(lambda self: os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_base_url = property(lambda self: os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"))
    llm_enabled = property(lambda self: boolean("LLM_ENABLED"))
    conversation_v2 = property(lambda self: boolean("TELEGRAM_CONVERSATION_V2"))
    allow_legacy_ingest_auth = property(lambda self: boolean("ALLOW_LEGACY_INGEST_AUTH"))
    production = property(lambda self: boolean("FITKIT_PRODUCTION"))
    llm_timeout_ms = property(lambda self: integer("LLM_TIMEOUT_MS", 8000, maximum=30000))
    llm_max_output_tokens = property(lambda self: integer("LLM_MAX_OUTPUT_TOKENS", 1024, maximum=4096))
    llm_daily_limit_per_user = property(lambda self: integer("LLM_DAILY_LIMIT_PER_USER", 50))
    llm_global_daily_limit = property(lambda self: integer("LLM_GLOBAL_DAILY_LIMIT", 500))
    action_confirm_ttl_seconds = property(lambda self: integer("ACTION_CONFIRM_TTL_SECONDS", 900, maximum=3600))
    dashboard_link_ttl_seconds = property(lambda self: integer("DASHBOARD_LINK_TTL_SECONDS", 900, maximum=3600))

    @property
    def llm_temperature(self) -> float:
        try:
            value = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        except ValueError:
            raise RuntimeError("Invalid LLM_TEMPERATURE") from None
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise RuntimeError("Invalid LLM_TEMPERATURE")
        return value

    @property
    def queue_key(self) -> str:
        from cryptography.fernet import Fernet
        key = os.getenv("FITKIT_QUEUE_KEY", "")
        try:
            Fernet(key.encode("ascii"))
        except (ValueError, UnicodeError):
            raise RuntimeError("FITKIT_QUEUE_KEY must be a Fernet key") from None
        return key

    @property
    def memory_key(self) -> str:
        from cryptography.fernet import Fernet
        key = os.getenv("FITKIT_MEMORY_KEY") or self.queue_key
        try:
            Fernet(key.encode("ascii"))
        except (ValueError, UnicodeError):
            raise RuntimeError("FITKIT_MEMORY_KEY must be a Fernet key") from None
        return key

    @property
    def beta_user_ids(self) -> set[int]:
        try:
            values = {int(v.strip()) for v in os.getenv("FITKIT_BETA_USER_IDS", "").split(",") if v.strip()}
        except ValueError:
            raise RuntimeError("Invalid FITKIT_BETA_USER_IDS") from None
        if any(v <= 0 for v in values):
            raise RuntimeError("Invalid FITKIT_BETA_USER_IDS")
        return values

    def validate(self) -> None:
        for name, descriptor in vars(type(self)).items():
            if isinstance(descriptor, property):
                getattr(self, name)
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required")
        if self.llm_enabled and not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is required when LLM_ENABLED=1")
        if self.production:
            if not self.beta_user_ids:
                raise RuntimeError("Production beta requires FITKIT_BETA_USER_IDS")
            if not self.telegram_bot_token or not self.telegram_webhook_secret:
                raise RuntimeError("Production beta requires Telegram credentials")
            url = urlsplit(self.public_base_url)
            if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
                raise RuntimeError("PUBLIC_BASE_URL must be an HTTPS origin")
            if self.allow_legacy_ingest_auth:
                raise RuntimeError("Legacy ingest authentication must be disabled in production")
            if self.conversation_v2 and not os.getenv("FITKIT_MEMORY_KEY"):
                raise RuntimeError("FITKIT_MEMORY_KEY is required for production conversation memory")


settings = Settings()
