"""Custom middleware for foreman."""

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from foreman.logging_info import generate_correlation_id


class LogCorrelationIdMiddleware:
    """
    Add a correlation ID to the bound logging context.

    A correlation ID is a unique identifier that is passed along with a request and included in all logs
    related to that request. This allows us to trace the flow of a request through the system, even when
    it spans multiple services.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Bind the context variables to the logging context."""
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        structlog.contextvars.bind_contextvars(
            correlation_id=generate_correlation_id(),
            method=scope["method"],
            path=scope["path"],
        )

        await self.app(scope, receive, send)

        structlog.contextvars.unbind_contextvars("correlation_id", "method", "path")

        return None
