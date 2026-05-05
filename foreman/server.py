"""Foreman FastAPI application and dispatch loop."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from foreman.executor import GitHubExecutor
from foreman.logging_info import configure as configure_logging
from foreman.middleware import LogCorrelationIdMiddleware
from foreman.otel import configure_otel
from foreman.protocol import LLMBackendRef, TaskContext, TaskMessage
from foreman.routers import health
from foreman.routers import queue as queue_router
from foreman.routers import result as result_router
from foreman.settings import settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from foreman.config import ForemanConfig
    from foreman.memory import MemoryStore
    from foreman.queue import TaskQueue
    from foreman.routers.agent import RouteTarget

configure_logging()

logger = structlog.get_logger(__name__)


class Dispatcher:
    """Orchestrates the harness dispatch loop: fetch memory → build task → enqueue → nudge agent.

    One :class:`Dispatcher` instance is created at startup and shared across
    the entire process.  Tasks are enqueued in the durable :class:`~foreman.queue.TaskQueue`
    before the agent is nudged; results are drained asynchronously by the background loop.

    Args:
        config: Validated :class:`~foreman.config.ForemanConfig`.
        memory: Open :class:`~foreman.memory.MemoryStore` instance.
        task_queue: Durable :class:`~foreman.queue.TaskQueue` instance.
    """

    def __init__(self, config: ForemanConfig, memory: MemoryStore, task_queue: TaskQueue) -> None:
        self._config = config
        self._memory = memory
        self._task_queue = task_queue
        self._executor = GitHubExecutor(token=str(config.identity.github_token), memory=memory)

    async def dispatch(self, event: dict[str, Any], route_target: RouteTarget) -> None:
        """Enqueue *event* for the agent described by *route_target* and nudge it.

        Sequence:
        1. Fetch memory summary for this repo+issue.
        2. Build a :class:`~foreman.protocol.TaskMessage`.
        3. Enqueue the task in the durable queue.
        4. Fire-and-forget ``POST <agent_url>/task`` nudge with ``{"task_id": ...}``.
           Network errors are logged and swallowed — the drain loop will retry.

        Args:
            event: Poller event dict with ``repo``, ``issue_number``, and ``payload`` keys.
            route_target: Resolved :class:`~foreman.routers.agent.RouteTarget`.
        """
        repo: str = event["repo"]
        issue_number: int = event["issue_number"]
        payload: dict[str, Any] = event["payload"]

        memory_summary = self._memory.get_memory_summary(repo, issue_number)
        task = TaskMessage(
            type="issue.triage",
            repo=repo,
            payload=payload,
            context=TaskContext(
                llm_backend=LLMBackendRef(
                    provider=self._config.llm.provider,
                    model=self._config.llm.model,
                ),
                memory_summary=memory_summary,
            ),
        )

        self._task_queue.enqueue(task, agent_url=route_target.url)
        logger.info("Task enqueued", task_id=task.task_id, repo=repo, issue_number=issue_number)

        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{route_target.url}/task",
                    json={"task_id": task.task_id},
                    timeout=5.0,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "Nudge to agent failed; task remains in queue",
                url=route_target.url,
                task_id=task.task_id,
                error=str(exc),
            )


async def _drain_loop(
    task_queue: TaskQueue,
    executor: GitHubExecutor,
    memory: MemoryStore,
    config: ForemanConfig,
    drain_event: asyncio.Event,
) -> None:
    """Drain completed tasks from the queue and execute their decisions.

    Wakes on *drain_event* or after ``config.queue.drain_interval_seconds``.
    Each ``(TaskMessage, DecisionMessage)`` pair returned by
    :meth:`~foreman.queue.TaskQueue.drain_completed` is passed to
    :meth:`~foreman.executor.GitHubExecutor.execute` and
    :meth:`~foreman.memory.MemoryStore.upsert_memory_summary`.

    Args:
        task_queue: The durable task queue.
        executor: GitHub action executor.
        memory: Memory store for summary updates.
        config: Runtime configuration (provides drain interval).
        drain_event: Asyncio event that wakes the loop early.
    """
    while True:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(drain_event.wait(), timeout=config.queue.drain_interval_seconds)
        drain_event.clear()

        try:
            pairs = task_queue.drain_completed()
        except Exception:
            logger.exception("drain_completed failed; skipping cycle")
            continue

        for task, decision in pairs:
            try:
                issue_number: int = task.payload.get("number", 0)
                executor.execute(
                    decision,
                    repo=task.repo,
                    issue_number=issue_number,
                    task_type=task.type,
                )
                summary = f"decision={decision.decision.value}; rationale={decision.rationale}"
                memory.upsert_memory_summary(task.repo, issue_number, summary)
                task_queue.mark_done(task.task_id)
            except Exception:
                logger.exception("Failed to process drain task", task_id=task.task_id)

        if pairs:
            logger.info("Drain loop processed tasks", count=len(pairs))


async def _requeue_loop(
    task_queue: TaskQueue,
    config: ForemanConfig,
) -> None:
    """Re-enqueue stale claimed tasks and fail exhausted ones.

    Runs on ``config.queue.requeue_interval_seconds`` interval.

    Args:
        task_queue: The durable task queue.
        config: Runtime configuration (provides requeue interval and max retries).
    """
    while True:
        await asyncio.sleep(config.queue.requeue_interval_seconds)
        requeued = task_queue.requeue_stale()
        failed = task_queue.fail_exhausted(max_retries=config.queue.max_retries)
        logger.info("Requeue cycle", requeued=requeued, failed=failed)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: start background drain and requeue loops.

    Reads ``app.state.task_queue``, ``app.state.executor``,
    ``app.state.memory``, and ``app.state.config`` which must be set
    by the caller (``__main__.py``) before the server starts.

    Args:
        app: The FastAPI application instance.

    Yields:
        None: Control passes to FastAPI while background loops are running.
    """
    task_queue: TaskQueue = app.state.task_queue
    executor: GitHubExecutor = app.state.executor
    memory: MemoryStore = app.state.memory
    config: ForemanConfig = app.state.config

    drain_event = asyncio.Event()
    app.state.drain_event = drain_event

    drain_task = asyncio.create_task(_drain_loop(task_queue, executor, memory, config, drain_event))
    requeue_task = asyncio.create_task(_requeue_loop(task_queue, config))

    logger.info("Background loops started")
    try:
        yield
    finally:
        drain_task.cancel()
        requeue_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await drain_task
        with contextlib.suppress(asyncio.CancelledError):
            await requeue_task
        logger.info("Background loops stopped")


app: FastAPI = FastAPI(
    title=settings.name,
    description=settings.name,
    docs_url="/swagger",
    swagger_ui_oauth2_redirect_url="/auth/callback",
    swagger_ui_parameters={
        "persistAuthorization": True,
    },
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(LogCorrelationIdMiddleware)

app.include_router(health.router)
app.include_router(queue_router.router)
app.include_router(result_router.router)

configure_otel(app, settings)
