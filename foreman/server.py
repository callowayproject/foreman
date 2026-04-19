"""Foreman FastAPI application and dispatch loop."""

from __future__ import annotations

import asyncio
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
from foreman.protocol import DecisionMessage, LLMBackendRef, TaskContext, TaskMessage
from foreman.routers import health
from foreman.settings import settings

if TYPE_CHECKING:
    from foreman.config import ForemanConfig
    from foreman.memory import MemoryStore
    from foreman.routers.agent import RouteTarget

configure_logging()

logger = structlog.get_logger(__name__)


class Dispatcher:
    """Orchestrates the harness dispatch loop: fetch memory → build task → POST to agent → execute.

    One :class:`Dispatcher` instance is created at startup and shared across
    the entire process.  A per-agent-URL :class:`asyncio.Lock` ensures that at
    most one task is dispatched concurrently to any given agent endpoint.

    Args:
        config: Validated :class:`~foreman.config.ForemanConfig`.
        memory: Open :class:`~foreman.memory.MemoryStore` instance.
    """

    def __init__(self, config: ForemanConfig, memory: MemoryStore) -> None:
        self._config = config
        self._memory = memory
        self._executor = GitHubExecutor(token=str(config.identity.github_token), memory=memory)
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, url: str) -> asyncio.Lock:
        """Return (creating if needed) the per-URL dispatch lock.

        Args:
            url: Agent base URL used as the lock key.

        Returns:
            The :class:`asyncio.Lock` for this URL.
        """
        if url not in self._locks:
            self._locks[url] = asyncio.Lock()
        return self._locks[url]

    async def dispatch(self, event: dict[str, Any], route_target: RouteTarget) -> None:
        """Dispatch *event* to the agent described by *route_target*.

        Sequence:
        1. Acquire per-agent-URL lock (serialise concurrent dispatches).
        2. Fetch memory summary for this repo+issue.
        3. Build a :class:`~foreman.protocol.TaskMessage`.
        4. POST to ``route_target.url/task``.
        5. On non-200 response or network error: log and return.
        6. Parse :class:`~foreman.protocol.DecisionMessage`.
        7. Execute actions via :class:`~foreman.executor.GitHubExecutor`.
        8. Write a summary to memory.

        Args:
            event: Poller event dict with ``repo``, ``issue_number``, and ``payload`` keys.
            route_target: Resolved :class:`~foreman.routers.agent.RouteTarget`.
        """
        repo: str = event["repo"]
        issue_number: int = event["issue_number"]
        payload: dict[str, Any] = event["payload"]
        agent = route_target.agent_assignment

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

        lock = self._get_lock(route_target.url)
        async with lock:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{route_target.url}/task",
                        json=task.model_dump(),
                        timeout=60.0,
                    )
            except httpx.HTTPError as exc:
                logger.error(
                    "HTTP error dispatching task to agent",
                    url=route_target.url,
                    error=str(exc),
                    repo=repo,
                    issue_number=issue_number,
                )
                return

        if response.status_code != 200:
            logger.error(
                "Agent returned non-200 response",
                url=route_target.url,
                status=response.status_code,
                body=response.text,
                repo=repo,
                issue_number=issue_number,
            )
            return

        decision = DecisionMessage.model_validate(response.json())

        self._executor.execute(
            decision,
            repo=repo,
            issue_number=issue_number,
            task_type=task.type,
            allow_close=agent.allow_close,
        )

        summary = f"decision={decision.decision.value}; rationale={decision.rationale}"
        self._memory.upsert_memory_summary(repo, issue_number, summary)

        logger.info(
            "Dispatch complete",
            repo=repo,
            issue_number=issue_number,
            decision=decision.decision.value,
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

configure_otel(app, settings)
