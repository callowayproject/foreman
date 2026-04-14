"""Tests for the foreman.middleware module."""

from unittest.mock import AsyncMock, patch

import pytest
import structlog

from foreman.middleware import LogCorrelationIdMiddleware


@pytest.fixture
def mock_asgi_app():
    """Fixture for a mock ASGI app."""
    return AsyncMock()


@pytest.fixture
def middleware(mock_asgi_app):
    """Fixture for LogCorrelationIdMiddleware instance with a mock app."""
    return LogCorrelationIdMiddleware(app=mock_asgi_app)


class TestLogCorrelationIdMiddleware:
    """Tests for the LogCorrelationId Middleware."""

    @pytest.mark.asyncio
    @patch("foreman.middleware.structlog.contextvars.bind_contextvars")
    @patch("foreman.middleware.generate_correlation_id")
    async def test_correlation_id_bound_to_contextvars(
        self, mock_generate_correlation_id, mock_bind_cxtvars, middleware, mock_asgi_app
    ):
        """The correlation ID should be bound to the contextvars when a request is made."""
        # Assemble
        mock_generate_correlation_id.return_value = "test-correlation-id"
        scope = {"type": "http", "method": "GET", "path": "/test"}
        receive = AsyncMock()
        send = AsyncMock()

        # Act
        await middleware(scope, receive, send)

        # Assert
        mock_generate_correlation_id.assert_called_once()
        mock_asgi_app.assert_awaited_once_with(scope, receive, send)
        assert mock_bind_cxtvars.call_args[1] == {
            "correlation_id": "test-correlation-id",
            "method": "GET",
            "path": "/test",
        }

    @pytest.mark.asyncio
    async def test_non_http_request_bypasses_middleware(self, middleware, mock_asgi_app):
        """A non-http request does not trigger the middleware."""
        # Assemble
        scope = {"type": "websocket"}  # Non HTTP request type
        receive = AsyncMock()
        send = AsyncMock()

        # Act
        await middleware(scope, receive, send)

        # Assert
        mock_asgi_app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    @patch("foreman.middleware.structlog.contextvars.unbind_contextvars")
    async def test_contextvars_unbind_after_request(self, mock_unbind_contextvars, middleware, mock_asgi_app):
        """The contextvars are unbound after the request is made."""
        # Assemble
        scope = {"type": "http", "method": "POST", "path": "/api"}
        receive = AsyncMock()
        send = AsyncMock()

        # Act
        await middleware(scope, receive, send)

        # Assert
        mock_unbind_contextvars.assert_called_once_with("correlation_id", "method", "path")
        mock_asgi_app.assert_awaited_once_with(scope, receive, send)
