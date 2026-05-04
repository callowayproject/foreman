"""End-to-end integration tests for the full issue triage pipeline.

Exercises the complete path:
    poller event → router → dispatcher (enqueue + nudge) → queue

No live GitHub API or LLM calls are made; boundaries are mocked at the
PyGithub and httpx layers.  The MemoryStore and TaskQueue use real temp-file
SQLite DBs.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from foreman.config import AgentAssignment, ForemanConfig, IdentityConfig, LLMConfig, RepoConfig
from foreman.memory import MemoryStore
from foreman.poller import GitHubPoller
from foreman.protocol import LLMBackendRef, TaskContext, TaskMessage
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


# ---------------------------------------------------------------------------
# Helpers for restart-resilience test
# ---------------------------------------------------------------------------


def _sqlite_status(db_path: Path, task_id: str) -> str:
    """Return the ``status`` column of a task_queue row, or ``'missing'``."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT status FROM task_queue WHERE task_id = ?", (task_id,)).fetchone()
        return row[0] if row else "missing"
    finally:
        conn.close()


def _sqlite_action_log(db_path: Path, repo: str, issue_id: int) -> list[tuple[str, str]]:
    """Return ``(decision, rationale)`` rows from ``action_log`` for *repo* / *issue_id*."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT decision, rationale FROM action_log WHERE repo = ? AND issue_id = ?",
            (repo, issue_id),
        ).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Integration: agent restart resilience (zero task loss)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAgentRestartResilience:
    """MVP acceptance criterion: zero task loss under a simulated agent restart.

    The test wires the harness queue endpoints (via a minimal in-process FastAPI
    app) to a real SQLite TaskQueue.  It uses the actual ForemanClient and agent
    startup-poll code, exercising the full claim → process → complete → drain
    path without any live network sockets.
    """

    def test_pending_task_claimed_on_restart(
        self,
        tmp_path: Path,
        config: ForemanConfig,
        mocker,
    ) -> None:
        """Task queued while the agent is down is picked up by the startup poll on restart.

        Flow:

        1. Enqueue a task while the agent is "down" (nudge never reaches it).
        2. Assert the task is ``pending`` in the queue.
        3. "Restart" the agent — lifespan startup poll fires ``next_task()``.
        4. Agent processes the task and calls ``complete_task()``.
        5. Assert the task is ``completed`` (or already ``done``).
        6. Drain manually and execute (simulates the drain loop).
        7. Assert task is ``done`` and ``action_log`` has an entry.
        """
        # Make foreman-client and agent importable without installation.
        _CLIENT_DIR = Path(__file__).parent.parent / "foreman-client"
        _AGENT_DIR = Path(__file__).parent.parent / "agents" / "issue-triage" / "issue_triage"
        for _d in (_CLIENT_DIR, _AGENT_DIR):
            if str(_d) not in sys.path:
                sys.path.insert(0, str(_d))

        from agent import app as agent_app  # noqa: PLC0415
        from foremanclient import ForemanClient  # noqa: PLC0415
        from foremanclient.models import DecisionMessage as ForemanDM  # noqa: PLC0415
        from foremanclient.models import DecisionType as ForemanDT  # noqa: PLC0415

        queue_db = tmp_path / "queue.db"
        memory_db = tmp_path / "memory.db"
        mocker.patch("foreman.executor.Github")

        with TaskQueue(queue_db) as task_queue, MemoryStore(memory_db) as memory:
            from foreman.executor import GitHubExecutor  # noqa: PLC0415
            from foreman.routers import queue as _qr  # noqa: PLC0415
            from foreman.routers import result as _rr  # noqa: PLC0415
            from foreman.routers.queue import get_drain_event as _qde  # noqa: PLC0415
            from foreman.routers.queue import get_task_queue as _gtq  # noqa: PLC0415
            from foreman.routers.result import get_drain_event as _rde  # noqa: PLC0415

            executor = GitHubExecutor(token="test-token", memory=memory)

            # Minimal in-process harness: queue endpoints only, no background loops.
            mini_harness = FastAPI(title="test-harness")
            mini_harness.include_router(_qr.router)
            mini_harness.include_router(_rr.router)
            mini_harness.dependency_overrides[_gtq] = lambda: task_queue
            mini_harness.dependency_overrides[_qde] = lambda: None
            mini_harness.dependency_overrides[_rde] = lambda: None

            with TestClient(mini_harness, raise_server_exceptions=True) as harness_tc:
                # -- Step 1: enqueue while agent is "down" (no nudge sent) --
                task = TaskMessage(
                    type="issue.triage",
                    repo="owner/repo",
                    payload={
                        "number": 42,
                        "title": "App crashes on startup",
                        "body": "Steps: run `app start`",
                        "state": "open",
                        "user": {"login": "reporter"},
                        "labels": [],
                    },
                    context=TaskContext(llm_backend=LLMBackendRef(provider="anthropic", model="claude-sonnet-4-6")),
                )
                task_queue.enqueue(task, agent_url="http://localhost:9001")

                # -- Step 2: task must be durable and pending --
                assert _sqlite_status(queue_db, task.task_id) == "pending"

                # Prepare a stub decision so triage requires no LLM call.
                stub_decision = ForemanDM(
                    task_id=task.task_id,
                    decision=ForemanDT.skip,
                    rationale="Integration test — skipping via stub",
                    actions=[],
                )
                mocker.patch("agent.triage", return_value=stub_decision)

                # Wire ForemanClient to use harness_tc as its HTTP transport.
                # Bypassing __init__ lets us inject the TestClient directly without env vars.
                foreman_client = ForemanClient.__new__(ForemanClient)
                foreman_client._agent_url = "http://localhost:9001"
                foreman_client._http = harness_tc
                # Prevent agent lifespan teardown from closing our shared harness_tc.
                foreman_client.close = lambda: None  # type: ignore[method-assign]

                # -- Step 3 & 4: "restart" agent — lifespan startup poll claims + processes --
                agent_app.state.client = foreman_client
                try:
                    with TestClient(agent_app, raise_server_exceptions=True):
                        pass  # startup poll completes inside lifespan __enter__
                finally:
                    del agent_app.state.client

                # -- Step 5: startup poll must have completed the task --
                status = _sqlite_status(queue_db, task.task_id)
                assert status in ("completed", "done"), (
                    f"Expected 'completed' or 'done' after agent restart, got {status!r}"
                )

                # -- Step 6: drain manually (simulates the drain loop) --
                pairs = task_queue.drain_completed()
                for drained_task, decision in pairs:
                    issue_number = drained_task.payload.get("number", 0)
                    executor.execute(
                        decision,
                        repo=drained_task.repo,
                        issue_number=issue_number,
                        task_type=drained_task.type,
                    )
                    memory.upsert_memory_summary(
                        drained_task.repo,
                        issue_number,
                        f"decision={decision.decision.value}",
                    )

                # -- Step 7: task is done and action_log is populated --
                assert _sqlite_status(queue_db, task.task_id) == "done"
                entries = _sqlite_action_log(memory_db, "owner/repo", 42)
                assert len(entries) >= 1, "action_log must have at least one entry"
                assert entries[0][0] == "skip"
