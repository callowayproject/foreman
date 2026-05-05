"""Tests for agents/issue-triage/agent.py — 202 protocol with ForemanClient."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Make the agent and foreman-client importable without installation.
_CLIENT_DIR = Path(__file__).parent.parent / "foreman-client"
_AGENT_DIR = Path(__file__).parent.parent / "agents" / "issue-triage" / "issue_triage"
for _dir in (_CLIENT_DIR, _AGENT_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from agent import app  # noqa: E402
from foremanclient import ForemanClient  # noqa: E402
from foremanclient.models import LLMBackendRef, TaskContext, TaskMessage  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(task_id: str = "test-uuid-001") -> TaskMessage:
    """Return a minimal TaskMessage for use in tests."""
    return TaskMessage(
        task_id=task_id,
        type="issue.triage",
        repo="owner/repo",
        payload={"issue_number": 42},
        context=TaskContext(llm_backend=LLMBackendRef(provider="anthropic", model="claude-haiku-4-5-20251001")),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_foreman_client() -> MagicMock:
    """Return a MagicMock with the ForemanClient spec; next_task() returns None by default."""
    mc = MagicMock(spec=ForemanClient)
    mc.next_task.return_value = None
    return mc


@pytest.fixture()
def client(mock_foreman_client: MagicMock) -> TestClient:
    """Return a TestClient with a mock ForemanClient injected via app.state."""
    app.state.client = mock_foreman_client
    with TestClient(app) as tc:
        yield tc
    del app.state.client


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """GET /health always returns 200."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """Health endpoint returns HTTP 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_body(self, client: TestClient) -> None:
        """Health endpoint returns a JSON body with status ok."""
        response = client.get("/health")
        assert response.json().get("status") == "ok"


# ---------------------------------------------------------------------------
# POST /task — validation
# ---------------------------------------------------------------------------


class TestTaskEndpointValidation:
    """POST /task validates the incoming nudge payload."""

    def test_invalid_json_returns_422(self, client: TestClient) -> None:
        """Malformed JSON body returns HTTP 422."""
        response = client.post("/task", content=b"not-json", headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_missing_task_id_returns_422(self, client: TestClient) -> None:
        """Missing task_id field returns HTTP 422."""
        response = client.post("/task", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /task — 202 Accepted + background task
# ---------------------------------------------------------------------------


class TestTaskEndpointAccepted:
    """POST /task returns 202 immediately and fires a background task."""

    def test_post_task_returns_202(self, client: TestClient) -> None:
        """POST /task returns 202 Accepted — not 200."""
        response = client.post("/task", json={"task_id": "test-uuid-001"})
        assert response.status_code == 202

    def test_background_task_calls_next_task(self, client: TestClient, mock_foreman_client: MagicMock) -> None:
        """Background task calls client.next_task() after nudge received."""
        # Startup poll already called next_task once; reset before POST
        mock_foreman_client.reset_mock()
        client.post("/task", json={"task_id": "test-uuid-001"})
        mock_foreman_client.next_task.assert_called()

    def test_next_task_returning_none_does_not_crash(self, client: TestClient, mock_foreman_client: MagicMock) -> None:
        """When next_task() returns None, background task completes without error."""
        mock_foreman_client.next_task.return_value = None
        response = client.post("/task", json={"task_id": "test-uuid-001"})
        assert response.status_code == 202

    def test_next_task_returning_task_calls_complete(
        self, client: TestClient, mock_foreman_client: MagicMock, mocker
    ) -> None:
        """When next_task() returns a task, complete_task() is called after triage."""
        task = _make_task()
        mock_foreman_client.next_task.return_value = task
        stub_decision = MagicMock()
        mocker.patch("agent.triage", return_value=stub_decision)
        client.post("/task", json={"task_id": task.task_id})
        mock_foreman_client.complete_task.assert_called_once_with(task.task_id, stub_decision)


# ---------------------------------------------------------------------------
# Startup poll
# ---------------------------------------------------------------------------


class TestStartupPoll:
    """Lifespan startup poll drains all queued tasks on boot."""

    def test_startup_poll_calls_next_task_once_when_queue_empty(self, mock_foreman_client: MagicMock) -> None:
        """Startup poll calls next_task() once when the queue is empty (returns None)."""
        app.state.client = mock_foreman_client
        with TestClient(app):
            pass
        del app.state.client
        assert mock_foreman_client.next_task.call_count == 1

    def test_startup_poll_drains_all_queued_tasks(self, mock_foreman_client: MagicMock, mocker) -> None:
        """Startup poll loops until next_task() returns None, processing each task."""
        tasks = [_make_task(f"t{i}") for i in range(3)]
        mock_foreman_client.next_task.side_effect = [*tasks, None]
        stub_decision = MagicMock()
        mocker.patch("agent.triage", return_value=stub_decision)

        app.state.client = mock_foreman_client
        with TestClient(app):
            pass
        del app.state.client

        # next_task called 4 times: 3 tasks + 1 None to break the loop
        assert mock_foreman_client.next_task.call_count == 4
        # All 3 tasks completed
        assert mock_foreman_client.complete_task.call_count == 3
