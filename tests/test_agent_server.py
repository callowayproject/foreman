"""Tests for agents/issue-triage/agent.py — FastAPI server scaffold."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make the agent importable without installing it as a package.
_AGENT_DIR = Path(__file__).parent.parent / "agents" / "issue-triage" / "issue_triage"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    """Return a synchronous TestClient for the agent FastAPI app."""
    return TestClient(app)


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
        data = response.json()
        assert data.get("status") == "ok"


# ---------------------------------------------------------------------------
# POST /task — validation
# ---------------------------------------------------------------------------


class TestTaskEndpointValidation:
    """POST /task validates the incoming TaskMessage."""

    def test_invalid_json_returns_422(self, client: TestClient) -> None:
        """Malformed JSON body returns HTTP 422."""
        response = client.post("/task", content=b"not-json", headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_missing_required_fields_returns_422(self, client: TestClient) -> None:
        """Missing required TaskMessage fields return HTTP 422."""
        response = client.post("/task", json={"task_id": "abc"})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /task — success path (triage logic stubbed)
# ---------------------------------------------------------------------------


def _valid_task_payload() -> dict:
    """Return a minimal valid TaskMessage payload."""
    return {
        "task_id": "test-uuid-001",
        "type": "issue.triage",
        "repo": "owner/repo",
        "payload": {
            "issue_number": 42,
            "title": "Bug: something is broken",
            "body": "Steps to reproduce...",
            "author": "user123",
            "labels": [],
        },
        "context": {
            "memory_summary": "",
            "llm_backend": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        },
    }


class TestTaskEndpointSuccess:
    """POST /task with a valid payload returns a DecisionMessage."""

    def test_valid_task_returns_200(self, client: TestClient, mocker) -> None:
        """Valid TaskMessage returns HTTP 200."""
        mocker.patch("agent.triage", return_value=_stub_decision("test-uuid-001"))
        response = client.post("/task", json=_valid_task_payload())
        assert response.status_code == 200

    def test_response_is_decision_message(self, client: TestClient, mocker) -> None:
        """Response body is a valid DecisionMessage."""
        mocker.patch("agent.triage", return_value=_stub_decision("test-uuid-001"))
        response = client.post("/task", json=_valid_task_payload())
        data = response.json()
        assert "task_id" in data
        assert "decision" in data
        assert "actions" in data

    def test_task_id_echoed_in_response(self, client: TestClient, mocker) -> None:
        """The task_id from the request is echoed in the response."""
        mocker.patch("agent.triage", return_value=_stub_decision("test-uuid-001"))
        response = client.post("/task", json=_valid_task_payload())
        data = response.json()
        assert data["task_id"] == "test-uuid-001"


def _stub_decision(task_id: str) -> dict:
    """Return a minimal DecisionMessage dict for stubbing triage()."""
    return {
        "task_id": task_id,
        "decision": "skip",
        "rationale": "stub",
        "actions": [],
    }
