import pytest

from api.services import telegram_client


class _FakeResponse:
    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        self.calls += 1
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


async def _noop_sleep(*args, **kwargs):
    return None


def _install(monkeypatch, responses):
    shared = _FakeAsyncClient(list(responses))

    def factory(*args, **kwargs):
        return shared

    monkeypatch.setattr(telegram_client.httpx, "AsyncClient", factory)
    monkeypatch.setattr(telegram_client.asyncio, "sleep", _noop_sleep)
    return shared


@pytest.mark.asyncio
async def test_retries_then_succeeds_after_429(monkeypatch):
    client = _install(
        monkeypatch,
        [
            _FakeResponse(429, {"ok": False}, headers={"Retry-After": "0"}),
            _FakeResponse(200, {"ok": True}),
        ],
    )

    await telegram_client.send_message(123, "hi")

    assert client.calls == 2


@pytest.mark.asyncio
async def test_retries_then_succeeds_after_5xx(monkeypatch):
    client = _install(
        monkeypatch,
        [
            _FakeResponse(500, {"ok": False}),
            _FakeResponse(200, {"ok": True}),
        ],
    )

    await telegram_client.send_message(123, "hi")

    assert client.calls == 2


@pytest.mark.asyncio
async def test_final_failure_raises_without_token(monkeypatch):
    client = _install(
        monkeypatch,
        [
            _FakeResponse(500, {"ok": False}),
            _FakeResponse(500, {"ok": False}),
            _FakeResponse(500, {"ok": False}),
        ],
    )

    with pytest.raises(RuntimeError, match="Telegram delivery failed"):
        await telegram_client.send_message(123, "hi")

    assert client.calls == 3


@pytest.mark.asyncio
async def test_answer_callback_query_is_best_effort(monkeypatch):
    client = _install(
        monkeypatch,
        [
            _FakeResponse(500, {"ok": False}),
            _FakeResponse(500, {"ok": False}),
            _FakeResponse(500, {"ok": False}),
        ],
    )

    # Should not raise even though every attempt failed.
    await telegram_client.answer_callback_query("cb_1", "done")

    assert client.calls == 3
