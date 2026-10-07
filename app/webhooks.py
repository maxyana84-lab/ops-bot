"""HTTP server: webhook receivers, liveness probe and Prometheus metrics."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .formatting import format_alertmanager, format_notify
from .metrics import WEBHOOKS_TOTAL

log = logging.getLogger(__name__)

Sender = Callable[[str], Awaitable[None]]
Formatter = Callable[[Mapping[str, Any]], str]


def _authorized(request: web.Request, secret: str) -> bool:
    supplied = request.headers.get("Authorization", "").encode()
    expected = f"Bearer {secret}".encode()
    return hmac.compare_digest(supplied, expected)


def build_web_app(secret: str, send: Sender) -> web.Application:
    app = web.Application(client_max_size=1024 * 1024)

    def receiver(source: str, formatter: Formatter):
        async def handler(request: web.Request) -> web.Response:
            if not _authorized(request, secret):
                WEBHOOKS_TOTAL.labels(source, "unauthorized").inc()
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                payload = await request.json()
            except ValueError:
                WEBHOOKS_TOTAL.labels(source, "bad_request").inc()
                return web.json_response({"error": "invalid JSON"}, status=400)
            if not isinstance(payload, dict):
                WEBHOOKS_TOTAL.labels(source, "bad_request").inc()
                return web.json_response({"error": "expected a JSON object"}, status=400)

            await send(formatter(payload))
            WEBHOOKS_TOTAL.labels(source, "ok").inc()
            return web.json_response({"ok": True})

        return handler

    async def healthz(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def metrics(_: web.Request) -> web.Response:
        return web.Response(body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    app.router.add_get("/healthz", healthz)
    app.router.add_get("/metrics", metrics)
    app.router.add_post("/webhook/alertmanager", receiver("alertmanager", format_alertmanager))
    app.router.add_post("/webhook/notify", receiver("notify", format_notify))
    return app
