"""POST /harness/result endpoint — drain-loop nudge from agents."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/harness",
    tags=["harness"],
)


class ResultNudge(BaseModel):
    """Request body for POST /harness/result.

    Attributes:
        task_id: ID of the completed task triggering the drain.
    """

    task_id: str


def get_drain_event(request: Request) -> asyncio.Event | None:
    """Retrieve the drain asyncio.Event from app state.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The drain asyncio.Event, or None if not yet initialised.
    """
    return getattr(request.app.state, "drain_event", None)


@router.post("/result")
async def harness_result(
    body: ResultNudge,
    drain_event: asyncio.Event | None = Depends(get_drain_event),
) -> Response:
    """Signal the drain loop that a completed task result is ready.

    Args:
        body: Request body containing the completed task ID.
        drain_event: Drain loop event from app state (injected).

    Returns:
        202 Accepted.
    """
    logger.debug("Drain nudge received", task_id=body.task_id)
    if drain_event is not None:
        drain_event.set()
    return Response(status_code=202)
