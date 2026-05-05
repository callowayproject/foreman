"""Issue triage agent — FastAPI server exposing POST /task and GET /health."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import structlog
from fastapi import BackgroundTasks, FastAPI
from foremanclient import ForemanClient
from pydantic import BaseModel

if TYPE_CHECKING:
    from foremanclient.models import DecisionMessage, TaskMessage

logger = structlog.get_logger(__name__)


def _get_client(application: FastAPI) -> ForemanClient:
    """Return the ForemanClient for *application*, creating it from env vars if needed.

    Args:
        application: The FastAPI application whose state holds the client.

    Returns:
        The :class:`~foremanclient.ForemanClient` instance for this agent.
    """
    if not hasattr(application.state, "client"):
        application.state.client = ForemanClient(
            harness_url=os.environ["FOREMAN_HARNESS_URL"],
            agent_url=os.environ["AGENT_URL"],
        )
    return application.state.client


def triage(task: TaskMessage) -> DecisionMessage:
    """Run triage logic on *task* and return a decision.

    Args:
        task: The incoming triage task from the harness.

    Returns:
        A :class:`~foremanclient.models.DecisionMessage` with decision, rationale, and actions.
    """
    from prompts.triage import run_triage

    return run_triage(task)


async def _process_task(client: ForemanClient, task: TaskMessage) -> None:
    """Call triage on *task* and report the completed decision to the harness.

    Args:
        client: The :class:`~foremanclient.ForemanClient` to use for completing the task.
        task: The :class:`~foremanclient.models.TaskMessage` to process.
    """
    decision = await asyncio.to_thread(triage, task)
    await asyncio.to_thread(client.complete_task, task.task_id, decision)


async def _poll_and_process(client: ForemanClient) -> None:
    """Claim the next pending task from the harness and process it if one exists.

    Args:
        client: The :class:`~foremanclient.ForemanClient` used to claim tasks.
    """
    task = await asyncio.to_thread(client.next_task)
    if task is not None:
        await _process_task(client, task)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: drain all tasks queued while the agent was down.

    Loops calling next_task() until the queue is empty so that accumulated
    pending tasks are not left stuck after an unclean restart.

    Args:
        application: The FastAPI application instance.
    """
    client = _get_client(application)
    while True:
        task = await asyncio.to_thread(client.next_task)
        if task is None:
            break
        await _process_task(client, task)
    yield
    client.close()


app = FastAPI(title="foreman-issue-triage", version="0.1.0", lifespan=_lifespan)


class TaskNudge(BaseModel):
    """Nudge payload sent by the harness when a new task is enqueued."""

    task_id: str
    """Identifier of the newly enqueued task."""


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        JSON body with ``{"status": "ok"}``.
    """
    return {"status": "ok"}


@app.post("/task", status_code=202)
async def handle_task(nudge: TaskNudge, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Accept a task nudge and process the task in the background.

    Args:
        nudge: The nudge payload containing the task_id from the harness.
        background_tasks: FastAPI background task queue.

    Returns:
        JSON body with ``{"status": "accepted"}``.
    """
    client = _get_client(app)
    background_tasks.add_task(_poll_and_process, client)
    return {"status": "accepted"}
