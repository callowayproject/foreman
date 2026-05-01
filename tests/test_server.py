"""Tests for the dispatch loop in foreman/server.py."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from foreman.config import AgentAssignment, ForemanConfig, IdentityConfig, LLMConfig, RepoConfig
from foreman.memory import MemoryStore
from foreman.protocol import ActionItem, DecisionMessage, DecisionType
from foreman.queue import TaskQueue
from foreman.routers.agent import RouteTarget
from foreman.server import Dispatcher, _drain_loop, _requeue_loop

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory(tmp_path: Path):
    """Provide a fresh MemoryStore backed by a temp-file DB."""
    with MemoryStore(tmp_path / "memory.db") as store:
        yield store


@pytest.fixture()
def task_queue(tmp_path: Path):
    """Provide a fresh TaskQueue backed by a temp-file DB."""
    with TaskQueue(tmp_path / "queue.db") as queue:
        yield queue


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


def _make_dispatcher(config, memory, task_queue, mocker) -> Dispatcher:
    """Construct a Dispatcher with Github patched out."""
    mocker.patch("foreman.executor.Github")
    return Dispatcher(config=config, memory=memory, task_queue=task_queue)


def _mock_async_client(*, post_return=None, post_side_effect=None):
    """Return a context-manager-compatible AsyncClient mock."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    if post_side_effect is not None:
        mock_client.post = AsyncMock(side_effect=post_side_effect)
    else:
        resp = MagicMock()
        resp.status_code = 202
        mock_client.post = AsyncMock(return_value=post_return or resp)
    return mock_client


# ---------------------------------------------------------------------------
# Dispatcher initialisation
# ---------------------------------------------------------------------------


class TestDispatcherInit:
    """Dispatcher can be constructed from config, memory, and task_queue."""

    def test_instantiates(self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, mocker) -> None:
        """Dispatcher is created without errors."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory, task_queue=task_queue)
        assert isinstance(dispatcher, Dispatcher)


# ---------------------------------------------------------------------------
# Dispatch: enqueue + nudge
# ---------------------------------------------------------------------------


class TestDispatchEnqueues:
    """dispatch() enqueues the task and sends a fire-and-forget nudge."""

    @pytest.mark.asyncio
    async def test_dispatch_enqueues_task_for_agent_url(
        self, config, memory, task_queue, route_target, mocker
    ) -> None:
        """dispatch() inserts the task into the queue for route_target.url."""
        dispatcher = _make_dispatcher(config, memory, task_queue, mocker)

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client()
            await dispatcher.dispatch(_make_event(), route_target)

        claimed = task_queue.claim_next("http://localhost:8001")
        assert claimed is not None
        assert claimed.repo == "owner/repo"

    @pytest.mark.asyncio
    async def test_dispatch_injects_memory_summary_into_enqueued_task(
        self, config, memory, task_queue, route_target, mocker
    ) -> None:
        """dispatch() fetches and injects the memory summary into the enqueued TaskMessage."""
        memory.upsert_memory_summary("owner/repo", 42, "Prior: labeled as bug.")
        dispatcher = _make_dispatcher(config, memory, task_queue, mocker)

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client()
            await dispatcher.dispatch(_make_event(issue_number=42), route_target)

        claimed = task_queue.claim_next("http://localhost:8001")
        assert claimed is not None
        assert claimed.context.memory_summary == "Prior: labeled as bug."

    @pytest.mark.asyncio
    async def test_dispatch_sends_nudge_to_agent_task_endpoint(
        self, config, memory, task_queue, route_target, mocker
    ) -> None:
        """dispatch() sends POST <agent_url>/task as a nudge."""
        dispatcher = _make_dispatcher(config, memory, task_queue, mocker)
        mock_post = AsyncMock(return_value=MagicMock(status_code=202))

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = mock_post
            mock_cls.return_value = mock_client
            await dispatcher.dispatch(_make_event(), route_target)

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert call_url == "http://localhost:8001/task"

    @pytest.mark.asyncio
    async def test_dispatch_nudge_body_contains_task_id(
        self, config, memory, task_queue, route_target, mocker
    ) -> None:
        """dispatch() nudge body is {"task_id": <uuid>} — not the full TaskMessage."""
        dispatcher = _make_dispatcher(config, memory, task_queue, mocker)
        mock_post = AsyncMock(return_value=MagicMock(status_code=202))

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = mock_post
            mock_cls.return_value = mock_client
            await dispatcher.dispatch(_make_event(), route_target)

        nudge_json = mock_post.call_args[1]["json"]
        assert set(nudge_json.keys()) == {"task_id"}
        assert nudge_json["task_id"]  # non-empty

    @pytest.mark.asyncio
    async def test_dispatch_does_not_parse_decision_from_agent(
        self, config, memory, task_queue, route_target, mocker
    ) -> None:
        """dispatch() does not parse a DecisionMessage from the agent response."""
        dispatcher = _make_dispatcher(config, memory, task_queue, mocker)

        # Agent returns a full DecisionMessage body — dispatch() must ignore it
        decision_body = DecisionMessage(
            task_id="task-001",
            decision=DecisionType.skip,
            rationale="Ignore me.",
            actions=[],
        ).model_dump()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = decision_body

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client
            # Must not raise even though we're not parsing the response
            await dispatcher.dispatch(_make_event(), route_target)

        # Task is in queue — executor was NOT called from dispatch
        claimed = task_queue.claim_next("http://localhost:8001")
        assert claimed is not None


# ---------------------------------------------------------------------------
# Dispatch: nudge errors are swallowed
# ---------------------------------------------------------------------------


class TestDispatchNudgeErrors:
    """dispatch() swallows nudge errors; the enqueue still happens."""

    @pytest.mark.asyncio
    async def test_nudge_connection_error_is_logged_and_swallowed(
        self, config, memory, task_queue, route_target, mocker
    ) -> None:
        """A network error on the nudge POST does not raise from dispatch()."""
        dispatcher = _make_dispatcher(config, memory, task_queue, mocker)

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client(post_side_effect=httpx.ConnectError("refused"))
            # Must not raise
            await dispatcher.dispatch(_make_event(), route_target)

    @pytest.mark.asyncio
    async def test_task_is_enqueued_even_when_nudge_fails(
        self, config, memory, task_queue, route_target, mocker
    ) -> None:
        """Task is in the queue even if the nudge POST throws."""
        dispatcher = _make_dispatcher(config, memory, task_queue, mocker)

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _mock_async_client(post_side_effect=httpx.ConnectError("refused"))
            await dispatcher.dispatch(_make_event(), route_target)

        claimed = task_queue.claim_next("http://localhost:8001")
        assert claimed is not None


# ---------------------------------------------------------------------------
# Background loops: drain
# ---------------------------------------------------------------------------


def _make_task_in_queue(task_queue: TaskQueue, agent_url: str = "http://agent") -> tuple:
    """Enqueue, claim, and complete a task; return (task_msg, decision_msg)."""
    from foreman.protocol import LLMBackendRef, TaskContext, TaskMessage

    task_msg = TaskMessage(
        task_id="drain-task-001",
        type="issue.triage",
        repo="owner/repo",
        payload={"number": 42, "title": "Crash", "body": ""},
        context=TaskContext(
            llm_backend=LLMBackendRef(provider="anthropic", model="claude-sonnet-4-6"),
        ),
    )
    decision_msg = DecisionMessage(
        task_id="drain-task-001",
        decision=DecisionType.label_and_respond,
        rationale="Bug confirmed.",
        actions=[ActionItem(type="add_label", label="bug")],
    )
    task_queue.enqueue(task_msg, agent_url=agent_url)
    task_queue.claim_next(agent_url)
    task_queue.complete(task_msg.task_id, decision_msg)
    return task_msg, decision_msg


class TestDrainLoop:
    """_drain_loop() drains completed tasks and calls executor + memory."""

    @pytest.mark.asyncio
    async def test_drain_loop_calls_executor_for_completed_task(
        self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, mocker
    ) -> None:
        """drain_loop calls executor.execute() for each completed task."""
        mock_executor = MagicMock()
        _make_task_in_queue(task_queue)

        drain_event = asyncio.Event()
        drain_event.set()

        loop_task = asyncio.create_task(_drain_loop(task_queue, mock_executor, memory, config, drain_event))
        await asyncio.sleep(0.01)
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task

        mock_executor.execute.assert_called_once()
        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["repo"] == "owner/repo"
        assert call_kwargs["issue_number"] == 42

    @pytest.mark.asyncio
    async def test_drain_loop_updates_memory_for_completed_task(
        self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue, mocker
    ) -> None:
        """drain_loop calls memory.upsert_memory_summary() for each completed task."""
        mock_executor = MagicMock()
        _make_task_in_queue(task_queue)

        drain_event = asyncio.Event()
        drain_event.set()

        loop_task = asyncio.create_task(_drain_loop(task_queue, mock_executor, memory, config, drain_event))
        await asyncio.sleep(0.01)
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task

        summary = memory.get_memory_summary("owner/repo", 42)
        assert summary is not None
        assert "label_and_respond" in summary

    @pytest.mark.asyncio
    async def test_drain_loop_wakes_on_drain_event(self, config: ForemanConfig, memory: MemoryStore, mocker) -> None:
        """drain_loop wakes immediately when drain_event is set."""
        mock_task_queue = MagicMock()
        mock_task_queue.drain_completed.return_value = []
        mock_executor = MagicMock()

        drain_event = asyncio.Event()

        loop_task = asyncio.create_task(_drain_loop(mock_task_queue, mock_executor, memory, config, drain_event))
        drain_event.set()
        await asyncio.sleep(0.01)
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task

        mock_task_queue.drain_completed.assert_called()

    @pytest.mark.asyncio
    async def test_drain_loop_cancelled_cleanly(self, config: ForemanConfig, memory: MemoryStore, mocker) -> None:
        """drain_loop raises no unhandled error when cancelled."""
        mock_task_queue = MagicMock()
        mock_task_queue.drain_completed.return_value = []
        mock_executor = MagicMock()
        drain_event = asyncio.Event()

        loop_task = asyncio.create_task(_drain_loop(mock_task_queue, mock_executor, memory, config, drain_event))
        await asyncio.sleep(0)
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task


# ---------------------------------------------------------------------------
# Background loops: requeue
# ---------------------------------------------------------------------------


class TestRequeueLoop:
    """_requeue_loop() calls requeue_stale() and fail_exhausted() on each cycle."""

    @pytest.mark.asyncio
    async def test_requeue_loop_calls_requeue_and_fail_exhausted(self) -> None:
        """requeue_loop calls both requeue_stale() and fail_exhausted() on each cycle."""
        from foreman.config import QueueConfig

        # Use requeue_interval_seconds=0 so asyncio.sleep(0) yields properly without mocking.
        config = ForemanConfig(
            identity=IdentityConfig(github_token="t", github_user="b"),
            llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
            repos=[],
            queue=QueueConfig(requeue_interval_seconds=0, max_retries=3),
        )
        mock_task_queue = MagicMock()
        mock_task_queue.requeue_stale.return_value = 0
        mock_task_queue.fail_exhausted.return_value = 0

        loop_task = asyncio.create_task(_requeue_loop(mock_task_queue, config))
        await asyncio.sleep(0.01)
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task

        mock_task_queue.requeue_stale.assert_called()
        mock_task_queue.fail_exhausted.assert_called_with(max_retries=3)

    @pytest.mark.asyncio
    async def test_requeue_loop_cancelled_cleanly(self, config: ForemanConfig) -> None:
        """requeue_loop raises no unhandled error when cancelled."""
        mock_task_queue = MagicMock()

        loop_task = asyncio.create_task(_requeue_loop(mock_task_queue, config))
        await asyncio.sleep(0)
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task
