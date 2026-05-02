"""Tests for foreman/executor.py — GitHubExecutor."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from foreman.executor import GitHubExecutor, UnknownActionError
from foreman.memory import MemoryStore
from foreman.protocol import ActionItem, DecisionMessage, DecisionType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    """Provide a fresh MemoryStore backed by a temp-file DB."""
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


@pytest.fixture()
def mock_issue(mocker):
    """Provide a mock PyGithub Issue."""
    return mocker.MagicMock()


@pytest.fixture()
def executor_and_issue(memory, mocker, mock_issue):
    """Provide a GitHubExecutor with the GitHub stack fully mocked."""
    mock_gh_cls = mocker.patch("foreman.executor.Github")
    mock_gh_cls.return_value.get_repo.return_value.get_issue.return_value = mock_issue
    executor = GitHubExecutor(token="test-token", memory=memory)
    return executor, mock_issue


def _make_decision(
    actions: list[ActionItem],
    decision: DecisionType = DecisionType.label_and_respond,
    rationale: str = "Test rationale.",
) -> DecisionMessage:
    """Build a DecisionMessage with the given actions."""
    return DecisionMessage(
        task_id="task-uuid-001",
        decision=decision,
        rationale=rationale,
        actions=actions,
    )


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestGitHubExecutorInit:
    """GitHubExecutor can be instantiated and wraps a Github client."""

    def test_instantiates_with_token_and_memory(self, memory: MemoryStore, mocker) -> None:
        """GitHubExecutor is created without errors given a token and MemoryStore."""
        mocker.patch("foreman.executor.Github")
        executor = GitHubExecutor(token="test-token", memory=memory)
        assert isinstance(executor, GitHubExecutor)

    def test_github_client_created_with_token(self, memory: MemoryStore, mocker) -> None:
        """Github client is initialised with the supplied token."""
        mock_gh_cls = mocker.patch("foreman.executor.Github")
        GitHubExecutor(token="my-token", memory=memory)
        mock_gh_cls.assert_called_once_with("my-token")


# ---------------------------------------------------------------------------
# add_label action
# ---------------------------------------------------------------------------


class TestExecuteAddLabel:
    """execute() with add_label actions."""

    def test_add_label_calls_add_to_labels(self, executor_and_issue) -> None:
        """add_label action calls issue.add_to_labels with the label name."""
        executor, issue = executor_and_issue
        decision = _make_decision([ActionItem(type="add_label", label="bug")])
        executor.execute(decision, repo="owner/repo", issue_number=42)
        issue.add_to_labels.assert_called_once_with("bug")

    def test_multiple_add_label_actions_called_in_order(self, executor_and_issue) -> None:
        """Multiple add_label actions each call add_to_labels in sequence."""
        executor, issue = executor_and_issue
        decision = _make_decision(
            [ActionItem(type="add_label", label="bug"), ActionItem(type="add_label", label="help wanted")]
        )
        executor.execute(decision, repo="owner/repo", issue_number=1)
        assert issue.add_to_labels.call_count == 2
        issue.add_to_labels.assert_any_call("bug")
        issue.add_to_labels.assert_any_call("help wanted")


# ---------------------------------------------------------------------------
# comment action
# ---------------------------------------------------------------------------


class TestExecuteComment:
    """execute() with comment actions."""

    def test_comment_calls_create_comment(self, executor_and_issue) -> None:
        """comment action calls issue.create_comment with the body string."""
        executor, issue = executor_and_issue
        decision = _make_decision([ActionItem(type="comment", body="Thanks for the report!")])
        executor.execute(decision, repo="owner/repo", issue_number=5)
        issue.create_comment.assert_called_once_with("Thanks for the report!")


# ---------------------------------------------------------------------------
# close_issue action
# ---------------------------------------------------------------------------


class TestExecuteCloseIssue:
    """execute() with close_issue actions."""

    def test_close_issue_calls_edit_when_allowed(self, executor_and_issue) -> None:
        """close_issue calls issue.edit(state='closed') when allow_close=True."""
        executor, issue = executor_and_issue
        decision = _make_decision([ActionItem(type="close_issue")], decision=DecisionType.close)
        executor.execute(decision, repo="owner/repo", issue_number=3, allow_close=True)
        issue.edit.assert_called_once_with(state="closed")

    def test_close_issue_skipped_when_allow_close_false(self, executor_and_issue) -> None:
        """close_issue does not call issue.edit when allow_close=False (default)."""
        executor, issue = executor_and_issue
        decision = _make_decision([ActionItem(type="close_issue")], decision=DecisionType.close)
        executor.execute(decision, repo="owner/repo", issue_number=3)
        issue.edit.assert_not_called()

    def test_allow_close_defaults_to_false(self, executor_and_issue) -> None:
        """allow_close defaults to False — close actions are skipped without explicit opt-in."""
        executor, issue = executor_and_issue
        decision = _make_decision([ActionItem(type="close_issue")], decision=DecisionType.close)
        executor.execute(decision, repo="owner/repo", issue_number=3)
        issue.edit.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown action type
# ---------------------------------------------------------------------------


class TestUnknownActionError:
    """execute() raises UnknownActionError for unrecognized action types."""

    def test_raises_for_unknown_type(self, executor_and_issue) -> None:
        """An unrecognized action type raises UnknownActionError."""
        executor, _ = executor_and_issue
        decision = _make_decision([ActionItem(type="assign_reviewer", reviewer="octocat")])
        with pytest.raises(UnknownActionError, match="assign_reviewer"):
            executor.execute(decision, repo="owner/repo", issue_number=1)

    def test_error_message_contains_action_type(self, executor_and_issue) -> None:
        """UnknownActionError message includes the offending action type name."""
        executor, _ = executor_and_issue
        decision = _make_decision([ActionItem(type="merge_pr")])
        with pytest.raises(UnknownActionError) as exc_info:
            executor.execute(decision, repo="owner/repo", issue_number=1)
        assert "merge_pr" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Action logging (before execution)
# ---------------------------------------------------------------------------


class TestActionLogging:
    """execute() logs the decision to action_log before making GitHub API calls."""

    def test_decision_written_to_action_log(self, executor_and_issue, memory: MemoryStore) -> None:
        """After execute(), the decision is present in the action_log table."""
        executor, _ = executor_and_issue
        decision = _make_decision([ActionItem(type="add_label", label="bug")])
        executor.execute(decision, repo="owner/repo", issue_number=10)

        conn = sqlite3.connect(memory.db_path)
        row = conn.execute("SELECT repo, issue_id, decision FROM action_log").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "owner/repo"
        assert row[1] == 10
        assert row[2] == "label_and_respond"

    def test_decision_logged_before_github_call_fails(self, memory: MemoryStore, mocker) -> None:
        """Decision is written to action_log even when a subsequent GitHub API call fails."""
        mock_gh_cls = mocker.patch("foreman.executor.Github")
        mock_issue = mocker.MagicMock()
        mock_issue.add_to_labels.side_effect = RuntimeError("network error")
        mock_gh_cls.return_value.get_repo.return_value.get_issue.return_value = mock_issue

        executor = GitHubExecutor(token="test-token", memory=memory)
        decision = _make_decision([ActionItem(type="add_label", label="bug")])

        with pytest.raises(RuntimeError, match="network error"):
            executor.execute(decision, repo="owner/repo", issue_number=7)

        conn = sqlite3.connect(memory.db_path)
        count = conn.execute("SELECT COUNT(*) FROM action_log").fetchone()[0]
        conn.close()
        assert count == 1, "log entry must exist even after GitHub failure"

    def test_task_type_stored_in_action_log(self, executor_and_issue, memory: MemoryStore) -> None:
        """execute() stores the task_type in action_log."""
        executor, _ = executor_and_issue
        decision = _make_decision([])
        executor.execute(decision, repo="owner/repo", issue_number=1, task_type="issue.triage")

        conn = sqlite3.connect(memory.db_path)
        row = conn.execute("SELECT task_type FROM action_log").fetchone()
        conn.close()
        assert row[0] == "issue.triage"

    def test_rationale_stored_in_action_log(self, executor_and_issue, memory: MemoryStore) -> None:
        """execute() stores the rationale in action_log."""
        executor, _ = executor_and_issue
        decision = _make_decision([], rationale="Confirmed bug in stack trace.")
        executor.execute(decision, repo="owner/repo", issue_number=2)

        conn = sqlite3.connect(memory.db_path)
        row = conn.execute("SELECT rationale FROM action_log").fetchone()
        conn.close()
        assert row[0] == "Confirmed bug in stack trace."


# ---------------------------------------------------------------------------
# Mixed action sequences
# ---------------------------------------------------------------------------


class TestMixedActions:
    """execute() handles multi-step action sequences correctly."""

    def test_label_then_comment(self, executor_and_issue) -> None:
        """A label+comment sequence calls both GitHub methods."""
        executor, issue = executor_and_issue
        decision = _make_decision(
            [
                ActionItem(type="add_label", label="bug"),
                ActionItem(type="comment", body="Confirmed."),
            ]
        )
        executor.execute(decision, repo="owner/repo", issue_number=9)
        issue.add_to_labels.assert_called_once_with("bug")
        issue.create_comment.assert_called_once_with("Confirmed.")

    def test_empty_actions_list_does_nothing(self, executor_and_issue, memory: MemoryStore) -> None:
        """execute() with an empty actions list logs the decision but calls no GitHub methods."""
        executor, issue = executor_and_issue
        decision = _make_decision([], decision=DecisionType.skip)
        executor.execute(decision, repo="owner/repo", issue_number=4)
        issue.add_to_labels.assert_not_called()
        issue.create_comment.assert_not_called()
        issue.edit.assert_not_called()

        conn = sqlite3.connect(memory.db_path)
        count = conn.execute("SELECT COUNT(*) FROM action_log").fetchone()[0]
        conn.close()
        assert count == 1, "decision must still be logged even with no actions"

    def test_get_issue_called_with_correct_number(self, memory: MemoryStore, mocker) -> None:
        """execute() fetches the correct issue number from PyGithub."""
        mock_gh_cls = mocker.patch("foreman.executor.Github")
        mock_repo = mocker.MagicMock()
        mock_gh_cls.return_value.get_repo.return_value = mock_repo
        executor = GitHubExecutor(token="test-token", memory=memory)

        decision = _make_decision([])
        executor.execute(decision, repo="owner/repo", issue_number=99)

        mock_repo.get_issue.assert_called_once_with(99)

    def test_get_repo_called_with_correct_name(self, memory: MemoryStore, mocker) -> None:
        """execute() fetches the correct repo from PyGithub."""
        mock_gh_cls = mocker.patch("foreman.executor.Github")
        mock_client = mocker.MagicMock()
        mock_gh_cls.return_value = mock_client
        executor = GitHubExecutor(token="test-token", memory=memory)

        decision = _make_decision([])
        executor.execute(decision, repo="myorg/myrepo", issue_number=1)

        mock_client.get_repo.assert_called_once_with("myorg/myrepo")
