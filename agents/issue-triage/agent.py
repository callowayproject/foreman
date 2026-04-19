"""Issue triage agent — FastAPI server exposing POST /task and GET /health."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="foreman-issue-triage", version="0.1.0")


# ---------------------------------------------------------------------------
# Protocol models (self-contained; mirrors foreman.protocol)
# ---------------------------------------------------------------------------


class LLMBackendRef(BaseModel):
    """Reference to the LLM backend the agent should use."""

    provider: str
    model: str


class TaskContext(BaseModel):
    """Context injected by the harness into each task."""

    llm_backend: LLMBackendRef
    memory_summary: Optional[str] = None


class TaskMessage(BaseModel):
    """Task message received from the harness."""

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    repo: str
    payload: dict[str, Any]
    context: TaskContext


class ActionItem(BaseModel):
    """A single action the harness should execute."""

    model_config = {"extra": "allow"}

    type: str


class DecisionMessage(BaseModel):
    """Decision returned to the harness."""

    task_id: str
    decision: str
    rationale: str
    actions: list[ActionItem] = []


# ---------------------------------------------------------------------------
# Triage logic (implemented in Task 15; placeholder here)
# ---------------------------------------------------------------------------


def triage(task: TaskMessage) -> DecisionMessage:
    """Run triage logic on *task* and return a decision.

    This placeholder is replaced by the full implementation in
    ``prompts/triage.py`` (Task 15).

    Args:
        task: The incoming triage task from the harness.

    Returns:
        A :class:`DecisionMessage` with decision, rationale, and actions.
    """
    from prompts.triage import run_triage

    return run_triage(task)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        JSON body with ``{"status": "ok"}``.
    """
    return {"status": "ok"}


@app.post("/task", response_model=DecisionMessage)
async def handle_task(task: TaskMessage) -> DecisionMessage:
    """Receive a triage task, run triage logic, and return a decision.

    Args:
        task: The incoming :class:`TaskMessage` from the harness.

    Returns:
        A :class:`DecisionMessage` with the triage decision and actions.
    """
    return triage(task)
