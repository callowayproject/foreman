"""Tests for foreman/routers/queue.py — queue HTTP endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from foreman.protocol import ActionItem, DecisionMessage, DecisionType, LLMBackendRef, TaskContext, TaskMessage
from foreman.queue import TaskQueue
from foreman.routers.queue import get_drain_event, get_task_queue
from foreman.server import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TASK_CONTEXT = TaskContext(llm_backend=LLMBackendRef(provider="anthropic", model="claude-sonnet-4-6"))


def _make_task(task_id: str = "task-1") -> TaskMessage:
    return TaskMessage(
        task_id=task_id,
        type="issue.triage",
        repo="owner/repo",
        payload={"issue": {"number": 1}},
        context=_TASK_CONTEXT,
    )


def _make_decision(task_id: str = "task-1") -> DecisionMessage:
    return DecisionMessage(
        task_id=task_id,
        decision=DecisionType.label_and_respond,
        rationale="Looks like a bug",
        actions=[ActionItem(type="add_label", label="bug")],
    )


@pytest.fixture()
def mock_queue() -> MagicMock:
    """Return a MagicMock with the TaskQueue spec."""
    return MagicMock(spec=TaskQueue)


@pytest.fixture()
def mock_drain_event() -> MagicMock:
    """Return a MagicMock standing in for asyncio.Event."""
    return MagicMock()


@pytest.fixture()
def client(mock_queue: MagicMock, mock_drain_event: MagicMock) -> TestClient:
    """Return a TestClient with queue dependencies overridden."""
    app.dependency_overrides[get_task_queue] = lambda: mock_queue
    app.dependency_overrides[get_drain_event] = lambda: mock_drain_event
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /queue/next
# ---------------------------------------------------------------------------


class TestQueueNext:
    """POST /queue/next — claim next pending task."""

    def test_returns_200_with_task_when_available(self, client: TestClient, mock_queue: MagicMock) -> None:
        """Returns 200 and TaskMessage JSON when a task is available."""
        task = _make_task("task-abc")
        mock_queue.claim_next.return_value = task

        response = client.post("/queue/next", json={"agent_url": "http://agent:9001"})

        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == "task-abc"
        assert body["type"] == "issue.triage"

    def test_claim_next_called_with_agent_url(self, client: TestClient, mock_queue: MagicMock) -> None:
        """claim_next is called with the agent_url from the request body."""
        mock_queue.claim_next.return_value = None

        client.post("/queue/next", json={"agent_url": "http://agent:9001"})

        mock_queue.claim_next.assert_called_once_with("http://agent:9001")

    def test_returns_204_when_queue_empty(self, client: TestClient, mock_queue: MagicMock) -> None:
        """Returns 204 No Content when claim_next returns None."""
        mock_queue.claim_next.return_value = None

        response = client.post("/queue/next", json={"agent_url": "http://agent:9001"})

        assert response.status_code == 204
        assert response.content == b""

    def test_response_is_valid_task_message_json(self, client: TestClient, mock_queue: MagicMock) -> None:
        """The 200 response body deserialises to a valid TaskMessage."""
        task = _make_task("task-xyz")
        mock_queue.claim_next.return_value = task

        response = client.post("/queue/next", json={"agent_url": "http://agent:9001"})

        assert response.status_code == 200
        parsed = TaskMessage.model_validate(response.json())
        assert parsed.task_id == "task-xyz"


# ---------------------------------------------------------------------------
# POST /queue/complete
# ---------------------------------------------------------------------------


class TestQueueComplete:
    """POST /queue/complete — store decision and signal drain."""

    def test_returns_202(self, client: TestClient) -> None:
        """Returns 202 Accepted."""
        decision = _make_decision("task-1")

        response = client.post(
            "/queue/complete", content=decision.model_dump_json(), headers={"content-type": "application/json"}
        )

        assert response.status_code == 202

    def test_calls_complete_with_task_id_and_decision(self, client: TestClient, mock_queue: MagicMock) -> None:
        """TaskQueue.complete() is called with the task_id and full DecisionMessage."""
        decision = _make_decision("task-1")

        client.post(
            "/queue/complete", content=decision.model_dump_json(), headers={"content-type": "application/json"}
        )

        mock_queue.complete.assert_called_once()
        args = mock_queue.complete.call_args
        assert args[0][0] == "task-1"
        stored: DecisionMessage = args[0][1]
        assert stored.decision == DecisionType.label_and_respond

    def test_sets_drain_event(self, client: TestClient, mock_drain_event: MagicMock) -> None:
        """The drain event is set after storing the decision."""
        decision = _make_decision("task-1")

        client.post(
            "/queue/complete", content=decision.model_dump_json(), headers={"content-type": "application/json"}
        )

        mock_drain_event.set.assert_called_once()


# ---------------------------------------------------------------------------
# POST /queue/heartbeat
# ---------------------------------------------------------------------------


class TestQueueHeartbeat:
    """POST /queue/heartbeat — extend claim window."""

    def test_returns_202(self, client: TestClient) -> None:
        """Returns 202 Accepted."""
        response = client.post("/queue/heartbeat", json={"task_id": "task-1"})

        assert response.status_code == 202

    def test_calls_heartbeat_with_task_id(self, client: TestClient, mock_queue: MagicMock) -> None:
        """TaskQueue.heartbeat() is called with the correct task_id."""
        client.post("/queue/heartbeat", json={"task_id": "task-99"})

        mock_queue.heartbeat.assert_called_once_with("task-99")
