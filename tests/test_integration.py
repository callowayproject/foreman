"""End-to-end integration tests for the full issue triage pipeline.

Exercises the complete path:
    poller event → router → dispatcher (enqueue + nudge) → queue

No live GitHub API or LLM calls are made; boundaries are mocked at the
PyGithub and httpx layers.  The MemoryStore and TaskQueue use real temp-file
SQLite DBs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foreman.config import AgentAssignment, ForemanConfig, IdentityConfig, LLMConfig, RepoConfig
from foreman.memory import MemoryStore
from foreman.poller import GitHubPoller
from foreman.queue import TaskQueue
from foreman.routers.agent import Router
from foreman.server import Dispatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO = "owner/repo"
_ISSUE_NUMBER = 42


def _make_event(issue_number: int = _ISSUE_NUMBER) -> dict[str, Any]:
    """Build a minimal poller-style event dict."""
    return {
        "repo": _REPO,
        "issue_number": issue_number,
        "payload": {
            "number": issue_number,
            "title": "App crashes on startup",
            "body": "Steps to reproduce: run `app start`",
            "state": "open",
            "user": {"login": "external-user"},
            "labels": [],
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory(tmp_path: Path):
    """Fresh MemoryStore backed by a real temp-file SQLite DB."""
    with MemoryStore(tmp_path / "memory.db") as store:
        yield store


@pytest.fixture()
def task_queue(tmp_path: Path):
    """Fresh TaskQueue backed by a real temp-file SQLite DB."""
    with TaskQueue(tmp_path / "queue.db") as queue:
        yield queue


@pytest.fixture()
def config() -> ForemanConfig:
    """ForemanConfig with one repo wired to an issue-triage agent."""
    return ForemanConfig(
        identity=IdentityConfig(github_token="test-token", github_user="bot"),
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        repos=[
            RepoConfig(
                owner="owner",
                name="repo",
                agents=[
                    AgentAssignment(
                        type="issue-triage",
                        config={"url": "http://localhost:9001"},
                        allow_close=False,
                    )
                ],
            )
        ],
    )


@pytest.fixture()
def router(config: ForemanConfig) -> Router:
    """Router with the issue-triage agent URL pre-registered."""
    r = Router(config)
    r.register_url("issue-triage", "http://localhost:9001")
    return r


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_async_client(*, post_side_effect=None):
    """Return a context-manager-compatible AsyncClient mock for the nudge POST."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        resp = MagicMock()
        resp.status_code = 202
        mock_client.post = AsyncMock(return_value=resp)
    return mock_client


# ---------------------------------------------------------------------------
# Full pipeline: event → router → dispatcher → queue
# ---------------------------------------------------------------------------


class TestFullTriagePipeline:
    """End-to-end: route an event, dispatch to agent (enqueue + nudge), verify queue state."""

    @pytest.mark.asyncio
    async def test_dispatch_enqueues_task_for_correct_agent(
        self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, router: Router, mocker
    ) -> None:
        """dispatch() inserts a TaskMessage into the queue with the agent URL."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory, task_queue=task_queue)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client()
            await dispatcher.dispatch(_make_event(), route_target)

        claimed = task_queue.claim_next("http://localhost:9001")
        assert claimed is not None
        assert claimed.repo == _REPO
        assert claimed.type == "issue.triage"

    @pytest.mark.asyncio
    async def test_dispatch_nudge_sends_task_id_to_agent(
        self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, router: Router, mocker
    ) -> None:
        """dispatch() nudge POST sends only the task_id (not the full TaskMessage)."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory, task_queue=task_queue)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        mock_post = AsyncMock(return_value=MagicMock(status_code=202))
        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = mock_post
            mock_cls.return_value = mock_client
            await dispatcher.dispatch(_make_event(), route_target)

        mock_post.assert_called_once()
        nudge_body = mock_post.call_args[1]["json"]
        assert set(nudge_body.keys()) == {"task_id"}

    @pytest.mark.asyncio
    async def test_prior_memory_summary_injected_into_enqueued_task(
        self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, router: Router, mocker
    ) -> None:
        """dispatch() injects the stored memory summary into the enqueued TaskMessage."""
        mocker.patch("foreman.executor.Github")
        memory.upsert_memory_summary(_REPO, _ISSUE_NUMBER, "Prior: labeled as bug on 2024-01-01.")
        dispatcher = Dispatcher(config=config, memory=memory, task_queue=task_queue)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client()
            await dispatcher.dispatch(_make_event(), route_target)

        claimed = task_queue.claim_next("http://localhost:9001")
        assert claimed is not None
        assert claimed.context.memory_summary == "Prior: labeled as bug on 2024-01-01."

    @pytest.mark.asyncio
    async def test_task_remains_in_queue_when_nudge_fails(
        self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, router: Router, mocker
    ) -> None:
        """Task is durably enqueued even if the nudge POST to the agent fails."""
        import httpx as _httpx

        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory, task_queue=task_queue)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client(post_side_effect=_httpx.ConnectError("refused"))
            await dispatcher.dispatch(_make_event(), route_target)

        claimed = task_queue.claim_next("http://localhost:9001")
        assert claimed is not None


# ---------------------------------------------------------------------------
# Poller feeds dispatcher via callback
# ---------------------------------------------------------------------------


class TestPollerFeedsDispatcher:
    """Tests that the poller callback chain routes and dispatches correctly."""

    @pytest.mark.asyncio
    async def test_poller_event_routed_and_enqueued(
        self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, router: Router, mocker
    ) -> None:
        """A polled issue travels through the callback into the dispatcher and is enqueued."""
        from pydantic import SecretStr

        mock_gh_cls = mocker.patch("foreman.poller.Github")
        mock_gh_repo = MagicMock()
        mock_gh_cls.return_value.get_repo.return_value = mock_gh_repo

        mock_issue = MagicMock()
        mock_issue.number = _ISSUE_NUMBER
        mock_issue.title = "App crash"
        mock_issue.body = "It crashes."
        mock_issue.state = "open"
        mock_issue.user.login = "external-user"
        mock_issue.labels = []

        mock_gh_repo.get_issues.return_value = [mock_issue]
        mock_gh_repo.get_collaborators.return_value = []

        mocker.patch("foreman.executor.Github")

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        dispatcher = Dispatcher(config=config, memory=memory, task_queue=task_queue)

        dispatched_events: list[dict[str, Any]] = []

        async def on_event(_: RepoConfig, event: dict[str, Any]) -> None:
            dispatched_events.append(event)
            route_target = router.route("issue.triage", event["repo"])
            if route_target is not None:
                await dispatcher.dispatch(event, route_target)

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client()
            await poller.poll_all(config.repos, on_event)

        assert len(dispatched_events) == 1
        assert dispatched_events[0]["issue_number"] == _ISSUE_NUMBER

        claimed = task_queue.claim_next("http://localhost:9001")
        assert claimed is not None
        assert claimed.repo == _REPO
