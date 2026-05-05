"""Tests for foreman/routers/result.py — POST /harness/result endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from foreman.routers.result import get_drain_event
from foreman.server import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_drain_event() -> MagicMock:
    """Return a MagicMock standing in for asyncio.Event."""
    return MagicMock()


@pytest.fixture()
def client(mock_drain_event: MagicMock) -> TestClient:
    """Return a TestClient with drain_event dependency overridden."""
    app.dependency_overrides[get_drain_event] = lambda: mock_drain_event
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /harness/result
# ---------------------------------------------------------------------------


class TestHarnessResult:
    """POST /harness/result — drain-loop nudge."""

    def test_returns_202(self, client: TestClient) -> None:
        """Returns 202 Accepted."""
        response = client.post("/harness/result", json={"task_id": "task-1"})

        assert response.status_code == 202

    def test_sets_drain_event(self, client: TestClient, mock_drain_event: MagicMock) -> None:
        """The drain event is set when the nudge is received."""
        client.post("/harness/result", json={"task_id": "task-1"})

        mock_drain_event.set.assert_called_once()

    def test_drain_event_none_does_not_raise(self) -> None:
        """Endpoint returns 202 even when drain_event is not initialised (None)."""
        app.dependency_overrides[get_drain_event] = lambda: None
        try:
            with TestClient(app) as c:
                response = c.post("/harness/result", json={"task_id": "task-1"})
            assert response.status_code == 202
        finally:
            app.dependency_overrides.clear()
