import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("LLM_ENABLED", "0")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("FITKIT_PRODUCTION", "0")
    monkeypatch.setenv("TELEGRAM_CONVERSATION_V2", "0")
    monkeypatch.setenv("FITKIT_QUEUE_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    monkeypatch.setenv("FITKIT_MEMORY_KEY", "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=")
