"""Translates DecisionMessage actions into GitHub API calls.

The harness executes all GitHub API calls — agents only produce action lists.
Credentials never enter agent containers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from github import Github

if TYPE_CHECKING:
    from foreman.memory import MemoryStore
    from foreman.protocol import ActionItem, DecisionMessage

logger = structlog.get_logger(__name__)


class UnknownActionError(Exception):
    """Raised when a DecisionMessage contains an unrecognized action type."""


class GitHubExecutor:
    """Translates a :class:`~foreman.protocol.DecisionMessage` into GitHub API calls.

    Logs the decision to the memory store *before* executing any GitHub API
    call, so the record exists even if a downstream call fails.

    Args:
        token: GitHub Personal Access Token for the bot account.
        memory: :class:`~foreman.memory.MemoryStore` used to log decisions.
    """

    def __init__(self, token: str, memory: MemoryStore) -> None:
        self._github = Github(token)
        self._memory = memory

    def execute(
        self,
        decision: DecisionMessage,
        repo: str,
        issue_number: int,
        task_type: str = "issue.triage",
        allow_close: bool = False,
    ) -> None:
        """Execute all actions in *decision*, logging the decision first.

        Writes the decision record to ``action_log`` before any GitHub API
        call is attempted.  Actions are executed in the order they appear in
        :attr:`~foreman.protocol.DecisionMessage.actions`.

        Args:
            decision: The agent's decision message containing actions to run.
            repo: Repository in ``owner/repo`` format.
            issue_number: GitHub issue number targeted by this decision.
            task_type: Task type string stored in ``action_log``.
            allow_close: Whether ``close_issue`` actions are permitted.

        Raises:
            UnknownActionError: If any action has an unrecognized ``type``.
        """
        self._memory.log_action(
            repo=repo,
            issue_id=issue_number,
            task_type=task_type,
            decision=decision.decision,
            rationale=decision.rationale,
            actions=decision.actions,
        )

        gh_repo = self._github.get_repo(repo)
        issue = gh_repo.get_issue(issue_number)

        for action in decision.actions:
            self._execute_action(action, issue, allow_close)

    def _execute_action(self, action: ActionItem, issue: Any, allow_close: bool) -> None:
        """Dispatch a single action to the appropriate PyGithub call.

        Args:
            action: The action to execute.
            issue: PyGithub ``Issue`` object for the target issue.
            allow_close: Whether ``close_issue`` is permitted.

        Raises:
            UnknownActionError: If ``action.type`` is not a known action type.
        """
        data = action.model_dump()
        action_type = data["type"]

        if action_type == "add_label":
            issue.add_to_labels(data["label"])
        elif action_type == "comment":
            issue.create_comment(data["body"])
        elif action_type == "close_issue":
            if allow_close:
                issue.edit(state="closed")
            else:
                logger.warning("close_issue skipped: allow_close is False for this agent config")
        else:
            raise UnknownActionError(f"Unknown action type: {action_type!r}")
