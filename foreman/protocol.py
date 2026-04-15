"""Pydantic models for the harness↔agent message protocol.

Task (harness → agent) and Decision (agent → harness) message contracts,
plus supporting types.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    """A single action to be executed by the harness after a decision.

    Extra fields are allowed to support future action types without schema changes.
    """

    model_config = {"extra": "allow"}

    type: str
    """Action type identifier (e.g. ``add_label``, ``comment``)."""


class LLMBackendRef(BaseModel):
    """Reference to the LLM backend the agent should use."""

    provider: str
    """LLM provider identifier (e.g. ``anthropic``, ``ollama``)."""

    model: str
    """Model name / identifier (e.g. ``claude-sonnet-4-6``)."""


class TaskContext(BaseModel):
    """Context injected by the harness into each task."""

    llm_backend: LLMBackendRef
    """LLM backend the agent should use for this task."""

    memory_summary: Optional[str] = None
    """LLM-generated summary of prior actions on this issue/repo, if any."""


class TaskMessage(BaseModel):
    """Task sent from the harness to an agent container.

    The harness generates a ``task_id`` automatically if not supplied.
    """

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this task (UUID4)."""

    type: str
    """Task type (e.g. ``issue.triage``)."""

    repo: str
    """Repository in ``owner/repo`` format."""

    payload: dict[str, Any]
    """Raw GitHub event payload."""

    context: TaskContext
    """Harness-injected context (memory summary, LLM backend)."""


class DecisionType(str, Enum):
    """Valid agent decision values."""

    label_and_respond = "label_and_respond"
    close = "close"
    escalate = "escalate"
    skip = "skip"


class DecisionMessage(BaseModel):
    """Decision returned from an agent to the harness."""

    task_id: str
    """Must match the ``task_id`` from the corresponding :class:`TaskMessage`."""

    decision: DecisionType
    """The agent's decision on how to handle the task."""

    rationale: str
    """Human-readable explanation of the decision."""

    actions: list[ActionItem] = []
    """Ordered list of actions for the harness to execute."""
