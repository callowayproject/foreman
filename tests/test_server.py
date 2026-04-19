"""Tests for the dispatch loop in foreman/server.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from foreman.config import AgentAssignment, ForemanConfig, IdentityConfig, LLMConfig, RepoConfig
from foreman.memory import MemoryStore
from foreman.protocol import ActionItem, DecisionMessage, DecisionType
from foreman.routers.agent import RouteTarget
from foreman.server import Dispatcher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory(tmp_path: Path):
    """Provide a fresh MemoryStore backed by a temp-file DB."""
    with MemoryStore(tmp_path / "memory.db") as store:
        yield store


@pytest.fixture()
def config() -> ForemanConfig:
    """Minimal ForemanConfig for tests."""
    return ForemanConfig(
        identity=IdentityConfig(github_token="test-token", github_user="bot"),
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        repos=[RepoConfig(owner="owner", name="repo", agents=[])],
    )


@pytest.fixture()
def route_target() -> RouteTarget:
    """A RouteTarget pointing to a local agent URL."""
    agent = AgentAssignment(
        type="issue-triage",
        config={"url": "http://localhost:8001"},
        allow_close=False,
    )
    return RouteTarget(url="http://localhost:8001", agent_assignment=agent)


@pytest.fixture()
def skip_decision() -> DecisionMessage:
    """A minimal skip DecisionMessage."""
    return DecisionMessage(
        task_id="task-001",
        decision=DecisionType.skip,
        rationale="Nothing to do.",
        actions=[],
    )


@pytest.fixture()
def label_decision() -> DecisionMessage:
    """A label_and_respond DecisionMessage with one action."""
    return DecisionMessage(
        task_id="task-001",
        decision=DecisionType.label_and_respond,
        rationale="Looks like a bug.",
        actions=[ActionItem(type="add_label", label="bug")],
    )


def _make_event(repo: str = "owner/repo", issue_number: int = 42) -> dict[str, Any]:
    """Build a minimal poller event dict."""
    return {
        "repo": repo,
        "issue_number": issue_number,
        "payload": {"number": issue_number, "title": "Test issue", "body": ""},
    }


# ---------------------------------------------------------------------------
# Dispatcher initialisation
# ---------------------------------------------------------------------------


class TestDispatcherInit:
    """Dispatcher can be constructed from config and memory."""

    def test_instantiates(self, config: ForemanConfig, memory: MemoryStore, mocker) -> None:
        """Dispatcher is created without errors."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory)
        assert isinstance(dispatcher, Dispatcher)


# ---------------------------------------------------------------------------
# Dispatch: happy path
# ---------------------------------------------------------------------------


class TestDispatchHappyPath:
    """dispatch() sends a task and executes the returned decision."""

    @pytest.mark.asyncio
    async def test_dispatch_posts_to_agent_url(self, config, memory, route_target, skip_decision, mocker) -> None:
        """dispatch() POSTs a TaskMessage to route_target.url + '/task'."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = skip_decision.model_dump()
        mock_post = AsyncMock(return_value=mock_response)

        with patch("foreman.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = mock_post
            mock_client_cls.return_value = mock_client

            await dispatcher.dispatch(_make_event(), route_target)

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert call_url == "http://localhost:8001/task"

    @pytest.mark.asyncio
    async def test_dispatch_injects_memory_summary_into_task(
        self, config, memory, route_target, skip_decision, mocker
    ) -> None:
        """dispatch() fetches and injects the memory summary before sending the task."""
        mocker.patch("foreman.executor.Github")
        memory.upsert_memory_summary("owner/repo", 42, "Prior: labeled as bug.")
        dispatcher = Dispatcher(config=config, memory=memory)

        posted_body: dict = {}

        async def capture_post(url, **kwargs):
            posted_body.update(kwargs.get("json", {}))
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = skip_decision.model_dump()
            return resp

        with patch("foreman.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = capture_post
            mock_client_cls.return_value = mock_client

            await dispatcher.dispatch(_make_event(issue_number=42), route_target)

        assert posted_body["context"]["memory_summary"] == "Prior: labeled as bug."

    @pytest.mark.asyncio
    async def test_dispatch_executes_actions_from_decision(
        self, config, memory, route_target, label_decision, mocker
    ) -> None:
        """dispatch() calls the executor with the returned DecisionMessage."""
        mock_gh_cls = mocker.patch("foreman.executor.Github")
        mock_issue = MagicMock()
        mock_gh_cls.return_value.get_repo.return_value.get_issue.return_value = mock_issue
        dispatcher = Dispatcher(config=config, memory=memory)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = label_decision.model_dump()

        with patch("foreman.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await dispatcher.dispatch(_make_event(), route_target)

        mock_issue.add_to_labels.assert_called_once_with("bug")

    @pytest.mark.asyncio
    async def test_dispatch_updates_memory_summary_after_decision(
        self, config, memory, route_target, label_decision, mocker
    ) -> None:
        """dispatch() writes a summary to memory after executing a decision."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = label_decision.model_dump()

        with patch("foreman.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await dispatcher.dispatch(_make_event(issue_number=42), route_target)

        summary = memory.get_memory_summary("owner/repo", 42)
        assert summary is not None


# ---------------------------------------------------------------------------
# Dispatch: agent HTTP errors
# ---------------------------------------------------------------------------


class TestDispatchAgentErrors:
    """dispatch() handles non-200 agent responses gracefully."""

    @pytest.mark.asyncio
    async def test_non_200_response_is_logged_and_skipped(self, config, memory, route_target, mocker) -> None:
        """A non-200 response from the agent logs and does not raise."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("foreman.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            # Should not raise
            await dispatcher.dispatch(_make_event(), route_target)

    @pytest.mark.asyncio
    async def test_connection_error_is_logged_and_skipped(self, config, memory, route_target, mocker) -> None:
        """A network error posting to the agent logs and does not raise."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory)

        with patch("foreman.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client

            # Should not raise
            await dispatcher.dispatch(_make_event(), route_target)


# ---------------------------------------------------------------------------
# Dispatch: concurrency lock
# ---------------------------------------------------------------------------


class TestDispatchConcurrencyLock:
    """dispatch() does not run concurrent tasks to the same agent URL."""

    @pytest.mark.asyncio
    async def test_second_dispatch_to_same_url_waits(
        self, config, memory, route_target, skip_decision, mocker
    ) -> None:
        """A second concurrent dispatch to the same URL is serialised."""
        import asyncio

        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory)

        call_order: list[str] = []

        async def slow_post(url, **kwargs):
            call_order.append("start")
            await asyncio.sleep(0)  # yield to event loop
            call_order.append("end")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = skip_decision.model_dump()
            return resp

        with patch("foreman.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = slow_post
            mock_client_cls.return_value = mock_client

            await asyncio.gather(
                dispatcher.dispatch(_make_event(), route_target),
                dispatcher.dispatch(_make_event(issue_number=99), route_target),
            )

        # Serialised: first task fully completes before second starts
        assert call_order == ["start", "end", "start", "end"]
