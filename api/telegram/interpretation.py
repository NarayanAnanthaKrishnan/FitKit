"""An interpretation prepared outside the domain transaction, injected by the worker."""
from contextlib import contextmanager
from contextvars import ContextVar
from api.llm.gateway import GatewayResult

_result = ContextVar("prepared_interpretation", default=None)
_opener_used = ContextVar("prepared_opener_used", default=False)


@contextmanager
def prepared_interpretation(result):
    token = _result.set(result)
    opener_token = _opener_used.set(False)
    try:
        yield
    finally:
        _opener_used.reset(opener_token)
        _result.reset(token)


def is_llm_enabled():
    return _result.get() is not None


async def interpret_free_text(text, *, user_id=None, context=None):
    return _result.get() or GatewayResult(fallback=True, error="not_prepared")


def take_prepared_opener() -> str | None:
    result = _result.get()
    if result is None or result.fallback or not result.opener or _opener_used.get():
        return None
    _opener_used.set(True)
    return result.opener
