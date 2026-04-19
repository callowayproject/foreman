"""Asyncio polling loop for GitHub repositories.

Polls all configured repositories concurrently, bounded by semaphore to
avoid GitHub API rate limits.  Issues authored by repo collaborators are
skipped by default.  Exponential backoff is applied on 403/429 responses.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog
from github import Auth, Github, GithubException

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import SecretStr

    from foreman.config import RepoConfig
    from foreman.memory import MemoryStore

logger = structlog.get_logger(__name__)

_DEFAULT_MAX_CONCURRENT = 5
"""Default maximum number of repos polled at the same time."""

_BACKOFF_BASE_SECONDS = 10.0
"""Initial backoff delay in seconds on rate-limit errors."""


class GitHubPoller:
    """Polls GitHub repositories for new/updated issues on a configured interval.

    Repositories are polled concurrently using :mod:`asyncio`, limited by a
    semaphore.  The last-polled timestamp for each repo is persisted so that
    only issues updated after that timestamp are emitted on subsequent polls.

    Args:
        token: GitHub Personal Access Token for the bot account.
        memory: :class:`~foreman.memory.MemoryStore` used to persist poll state.
        max_concurrent: Maximum number of repos polled simultaneously.
    """

    def __init__(self, token: SecretStr, memory: MemoryStore, max_concurrent: int = _DEFAULT_MAX_CONCURRENT) -> None:
        auth = Auth.Token(token.get_secret_value())
        self._github = Github(auth=auth)
        self._memory = memory
        self._max_concurrent = max_concurrent

    # ------------------------------------------------------------------
    # Single-repo poll (synchronous — runs in a thread via asyncio.to_thread)
    # ------------------------------------------------------------------

    def poll_repo(self, repo_config: RepoConfig) -> list[dict[str, Any]]:
        """Poll a single repository for new or updated issues.

        Fetches issues updated since the last recorded poll timestamp.
        Issues authored by collaborators are filtered out.
        Persists the new poll timestamp after a successful fetch.

        Args:
            repo_config: Configuration for the repository to poll.

        Returns:
            A list of event dicts, each with ``repo``, ``issue_number``, and
            ``payload`` keys.

        Raises:
            GithubException: Propagated for all GitHub API errors; the caller
                in :meth:`poll_all` handles rate-limit cases with backoff.
        """
        repo_name = f"{repo_config.owner}/{repo_config.name}"
        last_polled = self._memory.get_last_polled(repo_name)

        gh_repo = self._github.get_repo(repo_name)
        collaborator_logins = {c.login for c in gh_repo.get_collaborators()}

        get_issues_kwargs: dict[str, Any] = {"state": "open", "sort": "updated", "direction": "desc"}
        if last_polled is not None:
            get_issues_kwargs["since"] = last_polled

        issues = list(gh_repo.get_issues(**get_issues_kwargs))

        logger.info(
            "Polled repo",
            repo=repo_name,
            issues_found=len(issues),
            since=last_polled.isoformat() if last_polled else "beginning",
        )

        events: list[dict[str, Any]] = []
        for issue in issues:
            if issue.user.login in collaborator_logins:
                continue
            events.append(
                {
                    "repo": repo_name,
                    "issue_number": issue.number,
                    "payload": {
                        "number": issue.number,
                        "title": issue.title,
                        "body": issue.body,
                        "state": issue.state,
                        "user": {"login": issue.user.login},
                        "labels": [{"name": lbl.name} for lbl in issue.labels],
                    },
                }
            )

        self._memory.set_last_polled(repo_name, datetime.now(timezone.utc))
        return events

    # ------------------------------------------------------------------
    # Concurrent poll cycle (async)
    # ------------------------------------------------------------------

    async def poll_all(
        self,
        repos: list[RepoConfig],
        callback: Callable[[RepoConfig, dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Poll all repositories concurrently, respecting the semaphore limit.

        Each repo is polled in a thread via :func:`asyncio.to_thread` so
        blocking PyGithub calls do not block the event loop.  On 403/429
        errors, one retry is attempted after an exponential backoff delay.
        Other :class:`~github.GithubException` errors are re-raised.

        Args:
            repos: List of repository configs to poll this cycle.
            callback: Async callable invoked with ``(repo_config, event)`` for
                every emitted event.
        """
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def _poll_one(repo_cfg: RepoConfig) -> None:
            async with semaphore:
                await self._poll_with_backoff(repo_cfg, callback)

        await asyncio.gather(*[_poll_one(r) for r in repos])

    async def _poll_with_backoff(
        self,
        repo_cfg: RepoConfig,
        callback: Callable[[RepoConfig, dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Attempt to poll *repo_cfg*, applying exponential backoff on rate limits.

        Args:
            repo_cfg: Repository configuration to poll.
            callback: Async callable invoked per emitted event.

        Raises:
            GithubException: For non-rate-limit GitHub API errors.
        """
        delay = _BACKOFF_BASE_SECONDS
        for attempt in range(2):
            try:
                events = await asyncio.to_thread(self.poll_repo, repo_cfg)
                for event in events:
                    await callback(repo_cfg, event)
                return
            except GithubException as exc:
                if exc.status in (403, 429) and attempt == 0:
                    logger.warning(
                        "GitHub rate limit hit, backing off",
                        repo=f"{repo_cfg.owner}/{repo_cfg.name}",
                        status=exc.status,
                        backoff_seconds=delay,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                elif exc.status in (403, 429):
                    logger.error(
                        "GitHub rate limit persists after backoff; skipping repo this cycle",
                        repo=f"{repo_cfg.owner}/{repo_cfg.name}",
                        status=exc.status,
                    )
                    return
                else:
                    if exc.status == 401:
                        logger.critical(
                            "Bad GitHub credentials — check GITHUB_TOKEN; skipping repo this cycle",
                            repo=f"{repo_cfg.owner}/{repo_cfg.name}",
                            status=exc.status,
                        )
                    else:
                        logger.error(
                            "GitHub API error polling repo; skipping this cycle",
                            repo=f"{repo_cfg.owner}/{repo_cfg.name}",
                            status=exc.status,
                            error=str(exc),
                        )
                    return

    # ------------------------------------------------------------------
    # Continuous polling loop
    # ------------------------------------------------------------------

    async def run(
        self,
        repos: list[RepoConfig],
        interval_seconds: int,
        callback: Callable[[RepoConfig, dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Poll all repos in a continuous loop at *interval_seconds* frequency.

        Args:
            repos: Repositories to monitor.
            interval_seconds: Seconds to wait between poll cycles.
            callback: Async callable invoked per emitted event.
        """
        while True:
            await self.poll_all(repos, callback)
            await asyncio.sleep(interval_seconds)
