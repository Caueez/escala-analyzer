"""Bound request bodies and attach a request id and browser security headers."""

import json
import logging
from time import monotonic
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("escala.http")


class RequestSafetyMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int, production: bool) -> None:
        self.app, self.maximum, self.production = app, max_body_bytes, production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id, started = str(uuid4()), monotonic()
        scope.setdefault("state", {})["request_id"] = request_id
        size, messages = 0, []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.maximum:
                await JSONResponse(
                    {"detail": "Corpo da requisição acima do limite.", "request_id": request_id},
                    status_code=413,
                )(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        position = 0

        async def replay() -> Message:
            nonlocal position
            if position < len(messages):
                message = messages[position]
                position += 1
                return message
            return await receive()

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                security = {
                    "x-request-id": request_id,
                    "x-content-type-options": "nosniff",
                    "referrer-policy": "same-origin",
                    "x-frame-options": "DENY",
                    "permissions-policy": "camera=(), microphone=(), geolocation=()",
                    "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
                }
                if scope["path"].startswith("/api") or scope["path"] in {"/login", "/account"}:
                    security["cache-control"] = "no-store"
                if self.production:
                    security["strict-transport-security"] = "max-age=31536000; includeSubDomains"
                headers.extend((key.encode(), value.encode()) for key, value in security.items())
                message["headers"] = headers
                logger.info(
                    json.dumps(
                        {
                            "event": "http_request",
                            "request_id": request_id,
                            "method": scope["method"],
                            "path": scope["path"],
                            "status": message["status"],
                            "milliseconds": round((monotonic() - started) * 1000, 2),
                        }
                    )
                )
            await send(message)

        await self.app(scope, replay, secure_send)
