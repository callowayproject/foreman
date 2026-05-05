"""Queue HTTP endpoints for the queue-mediated agent protocol."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from foreman.protocol import DecisionMessage
from foreman.queue import TaskQueue

router = APIRouter(
    prefix="/queue",
    tags=["queue"],
)


class NextTaskRequest(BaseModel):
    """Request body for POST /queue/next.

    Attributes:
        agent_url: Base URL of the agent requesting a task.
    """

    agent_url: str


class HeartbeatRequest(BaseModel):
    """Request body for POST /queue/heartbeat.

    Attributes:
        task_id: ID of the task to heartbeat.
    """

    task_id: str


def get_task_queue(request: Request) -> TaskQueue:
    """Retrieve the TaskQueue from app state.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The TaskQueue instance attached to app state.
    """
    return request.app.state.task_queue


def get_drain_event(request: Request) -> asyncio.Event | None:
    """Retrieve the drain asyncio.Event from app state.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The drain asyncio.Event, or None if not yet initialised.
    """
    return getattr(request.app.state, "drain_event", None)


@router.post("/next")
async def queue_next(
    body: NextTaskRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
) -> Response:
    """Claim and return the next pending task for the requesting agent.

    Args:
        body: Request body containing the agent URL.
        task_queue: Task queue from app state (injected).

    Returns:
        200 with TaskMessage JSON when a task is available, 204 when the queue is empty.
    """
    task = task_queue.claim_next(body.agent_url)
    if task is None:
        return Response(status_code=204)
    return Response(content=task.model_dump_json(), status_code=200, media_type="application/json")


@router.post("/complete")
async def queue_complete(
    decision: DecisionMessage,
    task_queue: TaskQueue = Depends(get_task_queue),
    drain_event: asyncio.Event | None = Depends(get_drain_event),
) -> Response:
    """Store a completed task decision and signal the drain loop.

    Args:
        decision: The agent's DecisionMessage.
        task_queue: Task queue from app state (injected).
        drain_event: Drain loop event from app state (injected).

    Returns:
        202 Accepted.
    """
    task_queue.complete(decision.task_id, decision)
    if drain_event is not None:
        drain_event.set()
    return Response(status_code=202)


@router.post("/heartbeat")
async def queue_heartbeat(
    body: HeartbeatRequest,
    task_queue: TaskQueue = Depends(get_task_queue),
) -> Response:
    """Extend the claim window for an in-progress task.

    Args:
        body: Request body containing the task ID.
        task_queue: Task queue from app state (injected).

    Returns:
        202 Accepted.
    """
    task_queue.heartbeat(body.task_id)
    return Response(status_code=202)
