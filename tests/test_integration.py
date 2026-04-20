"""End-to-end integration tests for the full issue triage pipeline.

Exercises the complete path:
    poller event → router → dispatcher → executor (mocked GitHub API) → memory

No live GitHub API or LLM calls are made; boundaries are mocked at the
PyGithub and httpx layers.  The MemoryStore uses a real temp-file SQLite DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foreman.config import AgentAssignment, ForemanConfig, IdentityConfig, LLMConfig, RepoConfig
from foreman.memory import MemoryStore
from foreman.poller import GitHubPoller
from foreman.protocol import ActionItem, DecisionMessage, DecisionType
from foreman.routers.agent import Router
from foreman.server import Dispatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO = "owner/repo"
_ISSUE_NUMBER = 42


def _make_event(issue_number: int = _ISSUE_NUMBER) -> dict[str, Any]:
    """Build a minimal poller-style event dict."""
    return {
        "repo": _REPO,
        "issue_number": issue_number,
        "payload": {
            "number": issue_number,
            "title": "App crashes on startup",
            "body": "Steps to reproduce: run `app start`",
            "state": "open",
            "user": {"login": "external-user"},
            "labels": [],
        },
    }


def _label_and_respond_decision(task_id: str = "task-001") -> DecisionMessage:
    """Return a label_and_respond decision with add_label + comment actions."""
    return DecisionMessage(
        task_id=task_id,
        decision=DecisionType.label_and_respond,
        rationale="Reproducible crash — labeling as bug.",
        actions=[
            ActionItem(type="add_label", label="bug"),
            ActionItem(type="comment", body="Thanks for the report! Labeled as bug."),
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory(tmp_path: Path):
    """Fresh MemoryStore backed by a real temp-file SQLite DB."""
    with MemoryStore(tmp_path / "memory.db") as store:
        yield store


@pytest.fixture()
def config() -> ForemanConfig:
    """ForemanConfig with one repo wired to an issue-triage agent."""
    return ForemanConfig(
        identity=IdentityConfig(github_token="test-token", github_user="bot"),
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        repos=[
            RepoConfig(
                owner="owner",
                name="repo",
                agents=[
                    AgentAssignment(
                        type="issue-triage",
                        config={"url": "http://localhost:9001"},
                        allow_close=False,
                    )
                ],
            )
        ],
    )


@pytest.fixture()
def router(config: ForemanConfig) -> Router:
    """Router with the issue-triage agent URL pre-registered."""
    r = Router(config)
    r.register_url("issue-triage", "http://localhost:9001")
    return r


# ---------------------------------------------------------------------------
# Helper: patch httpx to return a canned agent decision
# ---------------------------------------------------------------------------


def _patch_httpx(decision: DecisionMessage):
    """Context manager that patches httpx.AsyncClient to return *decision*."""

    class _Ctx:
        def __enter__(self):
            self._patcher = patch("foreman.server.httpx.AsyncClient")
            mock_cls = self._patcher.start()
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=MagicMock(return_value=decision.model_dump()),
                )
            )
            mock_cls.return_value = mock_client
            self.mock_client = mock_client
            return self

        def __exit__(self, *_):
            self._patcher.stop()

    return _Ctx()


# ---------------------------------------------------------------------------
# Full pipeline: event → router → dispatcher → executor → memory
# ---------------------------------------------------------------------------


class TestFullTriagePipeline:
    """End-to-end: route an event, dispatch to agent, execute actions, update memory."""

    @pytest.mark.asyncio
    async def test_label_and_comment_applied_to_github_issue(
        self, config: ForemanConfig, memory: MemoryStore, router: Router, mocker
    ) -> None:
        """label_and_respond decision adds a label and comment on the GitHub issue."""
        mock_gh_cls = mocker.patch("foreman.executor.Github")
        mock_issue = MagicMock()
        mock_gh_cls.return_value.get_repo.return_value.get_issue.return_value = mock_issue

        dispatcher = Dispatcher(config=config, memory=memory)
        event = _make_event()
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        with _patch_httpx(_label_and_respond_decision()):
            await dispatcher.dispatch(event, route_target)

        mock_issue.add_to_labels.assert_called_once_with("bug")
        mock_issue.create_comment.assert_called_once_with("Thanks for the report! Labeled as bug.")

    @pytest.mark.asyncio
    async def test_memory_updated_after_decision(
        self, config: ForemanConfig, memory: MemoryStore, router: Router, mocker
    ) -> None:
        """Memory summary is written to the DB after a decision is executed."""
        mocker.patch("foreman.executor.Github")
        dispatcher = Dispatcher(config=config, memory=memory)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        with _patch_httpx(_label_and_respond_decision()):
            await dispatcher.dispatch(_make_event(), route_target)

        summary = memory.get_memory_summary(_REPO, _ISSUE_NUMBER)
        assert summary is not None
        assert "label_and_respond" in summary

    @pytest.mark.asyncio
    async def test_action_logged_to_db_before_github_call(
        self, config: ForemanConfig, memory: MemoryStore, router: Router, mocker
    ) -> None:
        """Decision is written to action_log before any GitHub API call is made."""
        import sqlite3

        call_order: list[str] = []

        mock_gh_cls = mocker.patch("foreman.executor.Github")
        mock_issue = MagicMock()

        def record_label(label: str) -> None:
            # Read DB inside the side-effect to confirm it was written first
            with sqlite3.connect(str(memory.db_path)) as conn:
                rows = conn.execute("SELECT decision FROM action_log").fetchall()
            call_order.append(f"db_rows={len(rows)},github_label={label}")

        mock_issue.add_to_labels.side_effect = record_label
        mock_gh_cls.return_value.get_repo.return_value.get_issue.return_value = mock_issue

        dispatcher = Dispatcher(config=config, memory=memory)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        with _patch_httpx(_label_and_respond_decision()):
            await dispatcher.dispatch(_make_event(), route_target)

        # action_log row existed when the GitHub API was called
        assert call_order == ["db_rows=1,github_label=bug"]

    @pytest.mark.asyncio
    async def test_prior_memory_summary_injected_into_task(
        self, config: ForemanConfig, memory: MemoryStore, router: Router, mocker
    ) -> None:
        """Second dispatch injects the memory summary from the first dispatch."""
        mocker.patch("foreman.executor.Github")
        memory.upsert_memory_summary(_REPO, _ISSUE_NUMBER, "Prior: labeled as bug on 2024-01-01.")
        dispatcher = Dispatcher(config=config, memory=memory)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        captured: dict[str, Any] = {}

        async def capture_post(_url: str, **kwargs: Any) -> MagicMock:
            captured["context"] = (kwargs.get("json") or {}).get("context", {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = DecisionMessage(
                task_id="t1",
                decision=DecisionType.skip,
                rationale="Already handled.",
            ).model_dump()
            return resp

        with patch("foreman.server.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = capture_post
            mock_cls.return_value = mock_client

            await dispatcher.dispatch(_make_event(), route_target)

        assert captured["context"]["memory_summary"] == "Prior: labeled as bug on 2024-01-01."

    @pytest.mark.asyncio
    async def test_close_action_skipped_when_allow_close_false(
        self, config: ForemanConfig, memory: MemoryStore, router: Router, mocker
    ) -> None:
        """close_issue action is not executed when allow_close is False."""
        mock_gh_cls = mocker.patch("foreman.executor.Github")
        mock_issue = MagicMock()
        mock_gh_cls.return_value.get_repo.return_value.get_issue.return_value = mock_issue

        dispatcher = Dispatcher(config=config, memory=memory)
        route_target = router.route("issue.triage", _REPO)
        assert route_target is not None

        close_decision = DecisionMessage(
            task_id="task-003",
            decision=DecisionType.close,
            rationale="Stale issue.",
            actions=[ActionItem(type="close_issue")],
        )

        with _patch_httpx(close_decision):
            await dispatcher.dispatch(_make_event(), route_target)

        mock_issue.edit.assert_not_called()


# ---------------------------------------------------------------------------
# Poller feeds dispatcher via callback
# ---------------------------------------------------------------------------


class TestPollerFeedsDispatcher:
    """Tests that the poller callback chain routes and dispatches correctly."""

    @pytest.mark.asyncio
    async def test_poller_event_routed_and_dispatched(
        self, config: ForemanConfig, memory: MemoryStore, router: Router, mocker
    ) -> None:
        """A polled issue travels through the callback into the dispatcher."""
        from pydantic import SecretStr

        # Mock PyGithub at the poller level to return one issue
        mock_gh_cls = mocker.patch("foreman.poller.Github")
        mock_gh_repo = MagicMock()
        mock_gh_cls.return_value.get_repo.return_value = mock_gh_repo

        mock_issue = MagicMock()
        mock_issue.number = _ISSUE_NUMBER
        mock_issue.title = "App crash"
        mock_issue.body = "It crashes."
        mock_issue.state = "open"
        mock_issue.user.login = "external-user"
        mock_issue.labels = []

        mock_gh_repo.get_issues.return_value = [mock_issue]
        mock_gh_repo.get_collaborators.return_value = []

        # Mock PyGithub at the executor level separately
        mock_exec_gh = mocker.patch("foreman.executor.Github")
        mock_exec_issue = MagicMock()
        mock_exec_gh.return_value.get_repo.return_value.get_issue.return_value = mock_exec_issue

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        dispatcher = Dispatcher(config=config, memory=memory)

        dispatched_events: list[dict[str, Any]] = []

        async def on_event(_repo_config: RepoConfig, event: dict[str, Any]) -> None:
            dispatched_events.append(event)
            route_target = router.route("issue.triage", event["repo"])
            if route_target is not None:
                await dispatcher.dispatch(event, route_target)

        with _patch_httpx(_label_and_respond_decision()):
            await poller.poll_all(config.repos, on_event)

        assert len(dispatched_events) == 1
        assert dispatched_events[0]["issue_number"] == _ISSUE_NUMBER

        # GitHub executor was called
        mock_exec_issue.add_to_labels.assert_called_once_with("bug")

        # Memory was updated
        summary = memory.get_memory_summary(_REPO, _ISSUE_NUMBER)
        assert summary is not None
