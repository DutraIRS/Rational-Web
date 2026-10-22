"""Structured request logging and optional OpenTelemetry tracing."""

from __future__ import annotations

import logging as std_logging
import math
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_request_id: ContextVar[str | None] = ContextVar("rational_request_id", default=None)


class Logging:
    """Per-app telemetry settings and structured log/span emission.

    Request and event timings use the standard-library logger by default.
    OpenTelemetry spans can be enabled when an OpenTelemetry provider is
    configured by the hosting application.
    """

    def __init__(
        self,
        *,
        logger: std_logging.Logger | None = None,
        request_id_header: str = "X-Request-ID",
        slow_render_threshold_ms: float = 100.0,
    ) -> None:
        self.logger = logger or std_logging.getLogger("rational")
        self.request_id_header = request_id_header
        self.slow_render_threshold_ms = slow_render_threshold_ms
        self._opentelemetry = False
        self._tracer: Any = None
        self.configure()

    @property
    def request_id(self) -> str | None:
        """The ID for the current request, or ``None`` outside a request."""
        return _request_id.get()

    def configure(
        self,
        *,
        request_id_header: str | None = None,
        slow_render_threshold_ms: float | None = None,
        opentelemetry: bool | None = None,
    ) -> None:
        """Update request ID, slow-render, or OpenTelemetry settings."""
        if request_id_header is not None and not _HEADER_NAME.fullmatch(request_id_header):
            raise ValueError("request_id_header must be a valid HTTP header name")
        if slow_render_threshold_ms is not None and (
            not math.isfinite(slow_render_threshold_ms) or slow_render_threshold_ms < 0
        ):
            raise ValueError("slow_render_threshold_ms must be a finite non-negative number")
        tracer = self._tracer
        if opentelemetry:
            try:
                from opentelemetry import trace
            except ImportError as exc:
                raise ImportError("OpenTelemetry tracing requires `pip install rational[telemetry]`") from exc
            tracer = trace.get_tracer("rational")
        if request_id_header is not None:
            self.request_id_header = request_id_header
        if slow_render_threshold_ms is not None:
            self.slow_render_threshold_ms = slow_render_threshold_ms
        if opentelemetry is not None:
            self._tracer = tracer
            self._opentelemetry = opentelemetry

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any]) -> Iterator[Any]:
        """Start a span when OpenTelemetry is enabled; otherwise act as a no-op."""
        if not self._opentelemetry:
            yield None
            return
        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span

    def record(self, event: str, *, level: int = std_logging.INFO, **fields: Any) -> None:
        """Emit one structured standard-library log record and span event."""
        request_id = self.request_id
        extra = {
            "rational_event": event,
            "rational_request_id": request_id,
            **{f"rational_{key}": value for key, value in fields.items()},
        }
        self.logger.log(level, event.replace(".", " "), extra=extra)
        if self._opentelemetry:
            from opentelemetry import trace

            span = trace.get_current_span()
            if span.is_recording():
                span.add_event(
                    event,
                    attributes={
                        key: value
                        for key, value in {"request.id": request_id, **fields}.items()
                        if isinstance(value, (str, bool, int, float))
                    },
                )

    def finish_span(self, span: Any, **attributes: Any) -> None:
        if span is not None:
            for name, value in attributes.items():
                if value is not None:
                    span.set_attribute(name, value)


class TelemetryMiddleware:
    """ASGI middleware that assigns request IDs and records HTTP timings."""

    def __init__(self, app: ASGIApp, telemetry: Logging) -> None:
        self.app = app
        self.telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_name = self.telemetry.request_id_header
        header_key = header_name.lower().encode("ascii")
        incoming = next(
            (value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == header_key), ""
        )
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["rational_request_id"] = request_id
        token: Token[str | None] = _request_id.set(request_id)
        started = time.perf_counter()
        status_code = 500
        failed: BaseException | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message = {
                    **message,
                    "headers": [(key, value) for key, value in message.get("headers", []) if key.lower() != header_key]
                    + [(header_key, request_id.encode("ascii"))],
                }
            await send(message)

        attributes = {
            "http.request.method": scope.get("method", ""),
            "url.path": scope.get("path", ""),
            "request.id": request_id,
        }
        try:
            with self.telemetry.span("rational.http.request", attributes) as span:
                try:
                    await self.app(scope, receive, send_with_request_id)
                except BaseException as exc:
                    failed = exc
                    raise
                finally:
                    duration_ms = (time.perf_counter() - started) * 1000
                    self.telemetry.finish_span(
                        span,
                        **{
                            "http.response.status_code": status_code,
                            "rational.request.duration_ms": duration_ms,
                            "error.type": type(failed).__name__ if failed is not None else None,
                        },
                    )
                    self.telemetry.record(
                        "http.request.completed",
                        level=std_logging.ERROR if failed is not None or status_code >= 500 else std_logging.INFO,
                        method=scope.get("method", ""),
                        path=scope.get("path", ""),
                        status_code=status_code,
                        duration_ms=duration_ms,
                        error_type=type(failed).__name__ if failed is not None else None,
                    )
        finally:
            _request_id.reset(token)
