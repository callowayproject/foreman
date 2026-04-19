"""Triage prompt construction and LLM response parsing.

The full implementation is provided in Task 15.  This stub satisfies type
checking and allows the agent server scaffold to be tested in isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent import DecisionMessage, TaskMessage


def run_triage(task: TaskMessage) -> DecisionMessage:
    """Run LLM-based triage on *task* and return a decision.

    Args:
        task: The incoming :class:`~agent.TaskMessage` from the harness.

    Returns:
        A :class:`~agent.DecisionMessage` with decision, rationale, and actions.

    Raises:
        NotImplementedError: Always — implemented in Task 15.
    """
    raise NotImplementedError("Triage logic implemented in Task 15")
