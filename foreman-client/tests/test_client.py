"""Tests for foremanclient/client.py — ForemanClient."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from foremanclient.client import ForemanClient, ForemanClientError
from foremanclient.models import ActionItem, DecisionMessage, DecisionType

_HARNESS_URL = "http://harness"
_AGENT_URL = "http://agent:9001"

_TASK_PAYLOAD: dict = {
    "task_id": "task-123",
    "type": "issue.triage",
    "repo": "owner/repo",
    "payload": {"number": 42},
    "context": {
        "llm_backend": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "memory_summary": None,
    },
}

_DECISION = DecisionMessage(
    task_id="task-123",
    decision=DecisionType.label_and_respond,
    rationale="Looks like a bug.",
    actions=[ActionItem(type="add_label", label="bug")],
)


def _make_client() -> ForemanClient:
    return ForemanClient(harness_url=_HARNESS_URL, agent_url=_AGENT_URL)


# ---------------------------------------------------------------------------
# next_task()
# ---------------------------------------------------------------------------


class TestNextTask:
    """Tests for ForemanClient.next_task()."""

    @respx.mock
    def test_returns_task_message_on_200(self) -> None:
        """200 response with valid JSON is parsed into a TaskMessage."""
        respx.post(f"{_HARNESS_URL}/queue/next").mock(return_value=httpx.Response(200, json=_TASK_PAYLOAD))
        client = _make_client()
        task = client.next_task()
        assert task is not None
        assert task.task_id == "task-123"
        assert task.repo == "owner/repo"

    @respx.mock
    def test_sends_agent_url_in_body(self) -> None:
        """next_task() sends agent_url in the request body."""
        route = respx.post(f"{_HARNESS_URL}/queue/next").mock(return_value=httpx.Response(200, json=_TASK_PAYLOAD))
        _make_client().next_task()
        assert route.called
        assert route.calls.last.request.content == b'{"agent_url":"http://agent:9001"}'

    @respx.mock
    def test_returns_none_on_204(self) -> None:
        """204 No Content means the queue is empty; returns None."""
        respx.post(f"{_HARNESS_URL}/queue/next").mock(return_value=httpx.Response(204))
        assert _make_client().next_task() is None

    @respx.mock
    def test_raises_on_server_error(self) -> None:
        """Non-2xx response raises ForemanClientError."""
        respx.post(f"{_HARNESS_URL}/queue/next").mock(return_value=httpx.Response(500, text="Internal error"))
        with pytest.raises(ForemanClientError) as exc_info:
            _make_client().next_task()
        assert exc_info.value.status_code == 500

    @respx.mock
    def test_raises_on_4xx(self) -> None:
        """4xx response raises ForemanClientError."""
        respx.post(f"{_HARNESS_URL}/queue/next").mock(return_value=httpx.Response(400, text="Bad request"))
        with pytest.raises(ForemanClientError) as exc_info:
            _make_client().next_task()
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# complete_task()
# ---------------------------------------------------------------------------


class TestCompleteTask:
    """Tests for ForemanClient.complete_task()."""

    @respx.mock
    def test_sends_decision_then_nudge(self) -> None:
        """complete_task() calls /queue/complete then /harness/result in order."""
        complete_route = respx.post(f"{_HARNESS_URL}/queue/complete").mock(return_value=httpx.Response(202))
        nudge_route = respx.post(f"{_HARNESS_URL}/harness/result").mock(return_value=httpx.Response(202))

        _make_client().complete_task("task-123", _DECISION)

        assert complete_route.called
        assert nudge_route.called

    @respx.mock
    def test_complete_endpoint_receives_decision_json(self) -> None:
        """Decision JSON is sent to /queue/complete."""
        route = respx.post(f"{_HARNESS_URL}/queue/complete").mock(return_value=httpx.Response(202))
        respx.post(f"{_HARNESS_URL}/harness/result").mock(return_value=httpx.Response(202))

        _make_client().complete_task("task-123", _DECISION)

        parsed = json.loads(route.calls.last.request.read())
        assert parsed["task_id"] == "task-123"
        assert parsed["decision"] == "label_and_respond"

    @respx.mock
    def test_nudge_endpoint_receives_task_id(self) -> None:
        """task_id is sent to /harness/result."""
        respx.post(f"{_HARNESS_URL}/queue/complete").mock(return_value=httpx.Response(202))
        route = respx.post(f"{_HARNESS_URL}/harness/result").mock(return_value=httpx.Response(202))

        _make_client().complete_task("task-123", _DECISION)

        body = json.loads(route.calls.last.request.read())
        assert body["task_id"] == "task-123"

    @respx.mock
    def test_raises_on_complete_error(self) -> None:
        """ForemanClientError raised when /queue/complete returns non-2xx."""
        respx.post(f"{_HARNESS_URL}/queue/complete").mock(return_value=httpx.Response(500, text="fail"))

        with pytest.raises(ForemanClientError) as exc_info:
            _make_client().complete_task("task-123", _DECISION)
        assert exc_info.value.status_code == 500

    @respx.mock
    def test_raises_on_nudge_error(self) -> None:
        """ForemanClientError raised when /harness/result returns non-2xx."""
        respx.post(f"{_HARNESS_URL}/queue/complete").mock(return_value=httpx.Response(202))
        respx.post(f"{_HARNESS_URL}/harness/result").mock(return_value=httpx.Response(503, text="unavailable"))

        with pytest.raises(ForemanClientError) as exc_info:
            _make_client().complete_task("task-123", _DECISION)
        assert exc_info.value.status_code == 503

    @respx.mock
    def test_nudge_not_called_when_complete_fails(self) -> None:
        """If /queue/complete fails, /harness/result is not called."""
        respx.post(f"{_HARNESS_URL}/queue/complete").mock(return_value=httpx.Response(500))
        nudge_route = respx.post(f"{_HARNESS_URL}/harness/result").mock(return_value=httpx.Response(202))

        with pytest.raises(ForemanClientError):
            _make_client().complete_task("task-123", _DECISION)

        assert not nudge_route.called


# ---------------------------------------------------------------------------
# heartbeat()
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Tests for ForemanClient.heartbeat()."""

    @respx.mock
    def test_sends_task_id(self) -> None:
        """heartbeat() sends task_id in the request body."""
        route = respx.post(f"{_HARNESS_URL}/queue/heartbeat").mock(return_value=httpx.Response(202))

        _make_client().heartbeat("task-123")

        assert route.called
        body = json.loads(route.calls.last.request.read())
        assert body["task_id"] == "task-123"

    @respx.mock
    def test_succeeds_on_202(self) -> None:
        """202 response completes without error."""
        respx.post(f"{_HARNESS_URL}/queue/heartbeat").mock(return_value=httpx.Response(202))
        _make_client().heartbeat("task-123")  # should not raise

    @respx.mock
    def test_raises_on_error(self) -> None:
        """ForemanClientError raised on non-2xx from /queue/heartbeat."""
        respx.post(f"{_HARNESS_URL}/queue/heartbeat").mock(return_value=httpx.Response(400, text="bad"))

        with pytest.raises(ForemanClientError) as exc_info:
            _make_client().heartbeat("task-123")
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# ForemanClient lifecycle (close / context manager)
# ---------------------------------------------------------------------------


class TestForemanClientLifecycle:
    """Tests for ForemanClient.close() and context manager support."""

    def test_close_closes_http_client(self) -> None:
        """close() delegates to the underlying httpx.Client.close()."""
        client = _make_client()
        with patch.object(client._http, "close") as mock_close:
            client.close()
        mock_close.assert_called_once()

    def test_context_manager_closes_on_exit(self) -> None:
        """Exiting the context manager calls close()."""
        client = _make_client()
        with patch.object(client._http, "close") as mock_close:
            with client:
                pass
        mock_close.assert_called_once()

    def test_context_manager_returns_client(self) -> None:
        """__enter__ returns the client instance."""
        client = _make_client()
        with patch.object(client._http, "close"):
            with client as c:
                assert c is client


# ---------------------------------------------------------------------------
# ForemanClientError
# ---------------------------------------------------------------------------


class TestForemanClientError:
    """Tests for the ForemanClientError exception."""

    def test_attributes(self) -> None:
        """status_code and message are accessible as attributes."""
        err = ForemanClientError(404, "not found")
        assert err.status_code == 404
        assert err.message == "not found"

    def test_str_representation(self) -> None:
        """str() includes status code and message."""
        err = ForemanClientError(500, "server error")
        assert "500" in str(err)
        assert "server error" in str(err)
