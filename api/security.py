"""Small application boundary protections and credential-safe logging."""
import logging
from fastapi.responses import JSONResponse
from api.config import settings


class AccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = str(args[2]).split("?", 1)[0]
            record.args = tuple(args)
        return True


def configure_logging():
    logging.getLogger("uvicorn.access").addFilter(AccessLogFilter())
    # HTTP client INFO logs contain bot-token URLs. Application metrics report
    # only statuses, timing, and token counts instead.
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True


class BoundaryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        original_send = send
        started = False
        async def protected_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            if message["type"] == "http.response.start" and path.startswith("/dashboard"):
                headers = list(message.get("headers", []))
                for name, value in [(b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer"), (b"x-content-type-options", b"nosniff")]:
                    headers = [(k, v) for k, v in headers if k.lower() != name]
                    headers.append((name, value))
                message = {**message, "headers": headers}
            await original_send(message)
        send = protected_send
        async def invoke(next_receive):
            try:
                await self.app(scope, next_receive, send)
            except Exception as exc:
                # SQL/provider exception strings may include user values.
                logging.getLogger(__name__).error("request.failed code=%s", type(exc).__name__)
                if not started:
                    await JSONResponse({"detail": "Request failed"}, status_code=500)(scope, next_receive, send)
                else:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
        if settings.production and (path.startswith(("/workouts", "/recommend", "/docs", "/redoc", "/internal")) or path in {"/health/summary", "/openapi.json"}):
            return await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
        # Enforce a real body limit, including chunked requests without a length header.
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    return
                size += len(message.get("body", b""))
                if size > 1_048_576:
                    return await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send)
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    break
            delivered = False
            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await receive()
            await invoke(bounded_receive)
        else:
            await invoke(receive)
