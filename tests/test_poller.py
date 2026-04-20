"""Tests for foreman/poller.py — GitHubPoller."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from foreman.config import RepoConfig
from foreman.memory import MemoryStore
from foreman.poller import GitHubPoller

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_issue(
    number: int = 1,
    author_login: str = "external-user",
    title: str = "Test issue",
    updated_at: datetime | None = None,
) -> MagicMock:
    """Build a mock PyGithub Issue."""
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.body = "Issue body text."
    issue.state = "open"
    issue.user.login = author_login
    issue.labels = []
    issue.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    issue.updated_at = updated_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return issue


def make_collaborator(login: str) -> MagicMock:
    """Build a mock PyGithub NamedUser."""
    c = MagicMock()
    c.login = login
    return c


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory(tmp_path: Path) -> Generator[MemoryStore, None, None]:
    """Provide a fresh MemoryStore backed by a temp-file DB."""
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


# ---------------------------------------------------------------------------
# poll_repo — basic behaviour
# ---------------------------------------------------------------------------


class TestPollRepo:
    """Tests for GitHubPoller.poll_repo() — synchronous single-repo poll."""

    def test_returns_events_for_open_issues(self, memory: MemoryStore, mocker) -> None:
        """poll_repo returns one event dict per open issue found."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = [make_issue(1), make_issue(2)]
        mock_repo.get_collaborators.return_value = []

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        events = poller.poll_repo(RepoConfig(owner="owner", name="repo"))

        assert len(events) == 2

    def test_event_has_required_fields(self, memory: MemoryStore, mocker) -> None:
        """Each event dict contains 'repo', 'issue_number', and 'payload'."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = [make_issue(7)]
        mock_repo.get_collaborators.return_value = []

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        events = poller.poll_repo(RepoConfig(owner="owner", name="repo"))

        assert len(events) == 1
        event = events[0]
        assert event["repo"] == "owner/repo"
        assert event["issue_number"] == 7
        assert "payload" in event

    def test_skips_issues_by_collaborators(self, memory: MemoryStore, mocker) -> None:
        """Issues authored by repo collaborators are not emitted."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = [
            make_issue(1, author_login="maintainer"),
            make_issue(2, author_login="external-user"),
        ]
        mock_repo.get_collaborators.return_value = [make_collaborator("maintainer")]

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        events = poller.poll_repo(RepoConfig(owner="owner", name="repo"))

        assert len(events) == 1
        assert events[0]["issue_number"] == 2

    def test_passes_since_to_get_issues_when_last_polled_set(self, memory: MemoryStore, mocker) -> None:
        """get_issues is called with 'since' when a last_polled timestamp exists."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = []
        mock_repo.get_collaborators.return_value = []

        last_polled = datetime(2024, 6, 1, tzinfo=timezone.utc)
        memory.set_last_polled("owner/repo", last_polled)

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        poller.poll_repo(RepoConfig(owner="owner", name="repo"))

        call_kwargs = mock_repo.get_issues.call_args
        assert call_kwargs.kwargs.get("since") == last_polled

    def test_get_issues_called_without_since_on_first_poll(self, memory: MemoryStore, mocker) -> None:
        """On the first poll (no prior timestamp), get_issues is called without 'since'."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = []
        mock_repo.get_collaborators.return_value = []

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        poller.poll_repo(RepoConfig(owner="owner", name="repo"))

        call_kwargs = mock_repo.get_issues.call_args
        assert "since" not in (call_kwargs.kwargs or {})

    def test_updates_last_polled_after_successful_poll(self, memory: MemoryStore, mocker) -> None:
        """poll_repo persists the last_polled timestamp after a successful poll."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = []
        mock_repo.get_collaborators.return_value = []

        assert memory.get_last_polled("owner/repo") is None

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        poller.poll_repo(RepoConfig(owner="owner", name="repo"))

        assert memory.get_last_polled("owner/repo") is not None

    def test_last_polled_survives_new_instance(self, memory: MemoryStore, mocker) -> None:
        """last_polled timestamp written in one poller instance is visible in the next."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = []
        mock_repo.get_collaborators.return_value = []

        poller1 = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        poller1.poll_repo(RepoConfig(owner="owner", name="repo"))
        ts1 = memory.get_last_polled("owner/repo")

        poller2 = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        poller2.poll_repo(RepoConfig(owner="owner", name="repo"))
        ts2 = memory.get_last_polled("owner/repo")

        assert ts1 is not None
        assert ts2 is not None
        assert ts2 >= ts1

    def test_payload_contains_issue_metadata(self, memory: MemoryStore, mocker) -> None:
        """The 'payload' field of each event includes issue number, title, body, and user."""
        mock_gh = mocker.patch("foreman.poller.Github")
        mock_repo = mocker.MagicMock()
        mock_gh.return_value.get_repo.return_value = mock_repo
        mock_repo.get_issues.return_value = [make_issue(3, author_login="alice", title="A bug")]
        mock_repo.get_collaborators.return_value = []

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        events = poller.poll_repo(RepoConfig(owner="owner", name="repo"))

        payload = events[0]["payload"]
        assert payload["number"] == 3
        assert payload["title"] == "A bug"
        assert payload["user"]["login"] == "alice"


# ---------------------------------------------------------------------------
# poll_all — concurrent polling
# ---------------------------------------------------------------------------


class TestPollAll:
    """Tests for GitHubPoller.poll_all() — async concurrent polling."""

    @pytest.mark.asyncio
    async def test_poll_all_calls_poll_repo_for_each_repo(self, memory: MemoryStore, mocker) -> None:
        """poll_all calls poll_repo once for every RepoConfig in the list."""
        mocker.patch("foreman.poller.Github")
        mock_poll = mocker.patch.object(GitHubPoller, "poll_repo", return_value=[])

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        repos = [
            RepoConfig(owner="org", name="repo1"),
            RepoConfig(owner="org", name="repo2"),
            RepoConfig(owner="org", name="repo3"),
        ]
        await poller.poll_all(repos, AsyncMock())

        assert mock_poll.call_count == 3

    @pytest.mark.asyncio
    async def test_poll_all_invokes_callback_for_each_event(self, memory: MemoryStore, mocker) -> None:
        """poll_all calls the callback for every event returned by poll_repo."""
        mocker.patch("foreman.poller.Github")
        events_map = {
            "org/repo1": [{"repo": "org/repo1", "issue_number": 1, "payload": {}}],
            "org/repo2": [{"repo": "org/repo2", "issue_number": 2, "payload": {}}],
        }

        def side_effect(repo_cfg: RepoConfig):
            return events_map.get(f"{repo_cfg.owner}/{repo_cfg.name}", [])

        mocker.patch.object(GitHubPoller, "poll_repo", side_effect=side_effect)

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        repos = [RepoConfig(owner="org", name="repo1"), RepoConfig(owner="org", name="repo2")]
        collected: list[dict] = []

        async def callback(repo_cfg: RepoConfig, event: dict) -> None:
            collected.append(event)

        await poller.poll_all(repos, callback)

        assert len(collected) == 2

    @pytest.mark.asyncio
    async def test_poll_all_with_empty_repo_list(self, memory: MemoryStore, mocker) -> None:
        """poll_all completes without error when given an empty repo list."""
        mocker.patch("foreman.poller.Github")
        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        await poller.poll_all([], AsyncMock())  # must not raise


# ---------------------------------------------------------------------------
# Exponential backoff on rate limits
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    """poll_all applies exponential backoff on 403/429 GitHub errors."""

    @pytest.mark.asyncio
    async def test_poll_all_retries_after_429(self, memory: MemoryStore, mocker) -> None:
        """poll_all retries the repo after a 429 rate-limit response."""
        from github import GithubException

        mocker.patch("foreman.poller.Github")
        sleep_mock = mocker.patch("foreman.poller.asyncio.sleep", new_callable=AsyncMock)

        call_count = 0

        def fail_then_succeed(repo_cfg: RepoConfig):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise GithubException(429, {"message": "rate limited"}, {})
            return []

        mocker.patch.object(GitHubPoller, "poll_repo", side_effect=fail_then_succeed)

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        await poller.poll_all([RepoConfig(owner="owner", name="repo")], AsyncMock())

        assert call_count == 2, "should retry once after 429"
        sleep_mock.assert_called_once()  # backoff sleep was called

    @pytest.mark.asyncio
    async def test_poll_all_retries_after_403(self, memory: MemoryStore, mocker) -> None:
        """poll_all retries the repo after a 403 forbidden response."""
        from github import GithubException

        mocker.patch("foreman.poller.Github")
        mocker.patch("foreman.poller.asyncio.sleep", new_callable=AsyncMock)

        call_count = 0

        def fail_then_succeed(repo_cfg: RepoConfig):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise GithubException(403, {"message": "forbidden"}, {})
            return []

        mocker.patch.object(GitHubPoller, "poll_repo", side_effect=fail_then_succeed)

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        await poller.poll_all([RepoConfig(owner="owner", name="repo")], AsyncMock())

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_poll_all_skips_repo_after_repeated_failures(self, memory: MemoryStore, mocker) -> None:
        """poll_all skips a repo if it fails repeatedly, without crashing."""
        from github import GithubException

        mocker.patch("foreman.poller.Github")
        mocker.patch("foreman.poller.asyncio.sleep", new_callable=AsyncMock)

        mocker.patch.object(
            GitHubPoller,
            "poll_repo",
            side_effect=GithubException(429, {"message": "rate limited"}, {}),
        )

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        # Must not raise
        await poller.poll_all([RepoConfig(owner="owner", name="repo")], AsyncMock())

    @pytest.mark.asyncio
    async def test_non_rate_limit_github_exception_logs_error_and_skips_repo(
        self, memory: MemoryStore, mocker
    ) -> None:
        """GithubExceptions other than 403/429 are logged as errors and the repo is skipped."""
        from github import GithubException

        mocker.patch("foreman.poller.Github")
        mock_logger = mocker.patch("foreman.poller.logger")

        mocker.patch.object(
            GitHubPoller,
            "poll_repo",
            side_effect=GithubException(500, {"message": "server error"}, {}),
        )

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        # Must not raise — error is logged and repo is skipped this cycle
        await poller.poll_all([RepoConfig(owner="owner", name="repo")], AsyncMock())

        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_bad_credentials_logs_critical_and_skips_repo(self, memory: MemoryStore, mocker) -> None:
        """A 401 BadCredentials error is logged at critical level and the repo is skipped."""
        from github import GithubException

        mocker.patch("foreman.poller.Github")
        mock_logger = mocker.patch("foreman.poller.logger")

        mocker.patch.object(
            GitHubPoller,
            "poll_repo",
            side_effect=GithubException(401, {"message": "Bad credentials"}, {}),
        )

        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        # Must not raise — critical is logged and repo is skipped
        await poller.poll_all([RepoConfig(owner="owner", name="repo")], AsyncMock())

        mock_logger.critical.assert_called_once()


# ---------------------------------------------------------------------------
# Semaphore / max_concurrent
# ---------------------------------------------------------------------------


class TestSemaphore:
    """GitHubPoller respects the max_concurrent semaphore limit."""

    def test_default_max_concurrent_is_five(self, memory: MemoryStore, mocker) -> None:
        """GitHubPoller defaults to max_concurrent=5."""
        mocker.patch("foreman.poller.Github")
        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory)
        assert poller._max_concurrent == 5

    def test_custom_max_concurrent_is_stored(self, memory: MemoryStore, mocker) -> None:
        """max_concurrent passed to __init__ is stored on the instance."""
        mocker.patch("foreman.poller.Github")
        poller = GitHubPoller(token=SecretStr("test-token"), memory=memory, max_concurrent=2)
        assert poller._max_concurrent == 2


# ---------------------------------------------------------------------------
# Memory — poll_state additions (integration with MemoryStore)
# ---------------------------------------------------------------------------


class TestPollStateMemory:
    """Tests for the poll_state additions to MemoryStore."""

    def test_get_last_polled_returns_none_for_unknown_repo(self, memory: MemoryStore) -> None:
        """get_last_polled returns None for a repo that has never been polled."""
        assert memory.get_last_polled("owner/never-polled") is None

    def test_set_and_get_last_polled_round_trips(self, memory: MemoryStore) -> None:
        """set_last_polled persists a timestamp that get_last_polled can retrieve."""
        ts = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        memory.set_last_polled("owner/repo", ts)
        result = memory.get_last_polled("owner/repo")
        assert result is not None
        assert result == ts

    def test_set_last_polled_overwrites_previous_value(self, memory: MemoryStore) -> None:
        """Calling set_last_polled twice updates the stored timestamp."""
        ts1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2024, 6, 1, tzinfo=timezone.utc)
        memory.set_last_polled("owner/repo", ts1)
        memory.set_last_polled("owner/repo", ts2)
        assert memory.get_last_polled("owner/repo") == ts2

    def test_poll_state_is_per_repo(self, memory: MemoryStore) -> None:
        """Each repo has its own independent last_polled timestamp."""
        ts1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2024, 6, 1, tzinfo=timezone.utc)
        memory.set_last_polled("org/repo-a", ts1)
        memory.set_last_polled("org/repo-b", ts2)
        assert memory.get_last_polled("org/repo-a") == ts1
        assert memory.get_last_polled("org/repo-b") == ts2
