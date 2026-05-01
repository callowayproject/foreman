"""Foreman FastAPI application and dispatch loop."""

from __future__ import annotations

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


app: FastAPI = FastAPI(
    title=settings.name,
    description=settings.name,
    docs_url="/swagger",
    swagger_ui_oauth2_redirect_url="/auth/callback",
    swagger_ui_parameters={
        "persistAuthorization": True,
    },
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
