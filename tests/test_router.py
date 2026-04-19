"""Tests for foreman/routers/agent.py — Router."""

from __future__ import annotations

import pytest

from foreman.config import AgentAssignment, ForemanConfig, IdentityConfig, LLMConfig, RepoConfig
from foreman.routers.agent import RouteTarget, Router, RoutingError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    repos: list[RepoConfig] | None = None,
) -> ForemanConfig:
    """Build a minimal ForemanConfig with the given repos."""
    return ForemanConfig(
        identity=IdentityConfig(github_token="tok", github_user="bot"),
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        repos=repos or [],
    )


def _make_repo(
    owner: str = "owner",
    name: str = "repo",
    agents: list[AgentAssignment] | None = None,
) -> RepoConfig:
    """Build a minimal RepoConfig."""
    return RepoConfig(owner=owner, name=name, agents=agents or [])


def _make_agent(
    agent_type: str = "issue-triage",
    url: str = "http://localhost:8001",
    event_types: list[str] | None = None,
    allow_close: bool = False,
) -> AgentAssignment:
    """Build an AgentAssignment with url (and optional explicit event_types) in config."""
    cfg: dict = {"url": url}
    if event_types is not None:
        cfg["event_types"] = event_types
    return AgentAssignment(type=agent_type, config=cfg, allow_close=allow_close)


# ---------------------------------------------------------------------------
# Basic routing
# ---------------------------------------------------------------------------


class TestRouterBasicRouting:
    """Router.route() returns the correct RouteTarget for known events."""

    def test_routes_issue_event_to_issue_triage_agent(self) -> None:
        """issue.triage event for a known repo routes to the issue-triage agent."""
        agent = _make_agent("issue-triage", url="http://localhost:8001")
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        result = router.route("issue.triage", "owner/repo")

        assert result is not None
        assert result.url == "http://localhost:8001"

    def test_route_target_carries_agent_assignment(self) -> None:
        """RouteTarget.agent_assignment is the matching AgentAssignment."""
        agent = _make_agent("issue-triage", url="http://localhost:8001", allow_close=True)
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        result = router.route("issue.triage", "owner/repo")

        assert result is not None
        assert result.agent_assignment.allow_close is True
        assert result.agent_assignment.type == "issue-triage"


# ---------------------------------------------------------------------------
# Unmapped event type → None
# ---------------------------------------------------------------------------


class TestUnmappedEventType:
    """Router.route() returns None for event types not handled by any agent."""

    def test_unmapped_event_type_returns_none(self) -> None:
        """An event type with no matching agent returns None (not an error)."""
        agent = _make_agent("issue-triage", url="http://localhost:8001")
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        result = router.route("pull_request.opened", "owner/repo")

        assert result is None

    def test_no_agents_in_repo_returns_none(self) -> None:
        """A repo with no agents configured returns None for any event type."""
        config = _make_config([_make_repo(agents=[])])
        router = Router(config)

        result = router.route("issue.triage", "owner/repo")

        assert result is None


# ---------------------------------------------------------------------------
# Unmapped repo → RoutingError
# ---------------------------------------------------------------------------


class TestUnmappedRepo:
    """Router.route() raises RoutingError when the repo is not configured."""

    def test_unknown_repo_raises_routing_error(self) -> None:
        """A repo not in the config raises RoutingError."""
        config = _make_config([])
        router = Router(config)

        with pytest.raises(RoutingError, match="owner/unknown"):
            router.route("issue.triage", "owner/unknown")

    def test_routing_error_message_contains_repo_name(self) -> None:
        """RoutingError message includes the unknown repo name."""
        config = _make_config([_make_repo(owner="acme", name="myrepo")])
        router = Router(config)

        with pytest.raises(RoutingError) as exc_info:
            router.route("issue.triage", "acme/OTHER")
        assert "acme/OTHER" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Multiple agents per repo
# ---------------------------------------------------------------------------


class TestMultipleAgentsPerRepo:
    """Router handles repos with multiple agents, each covering different event types."""

    def test_routes_to_correct_agent_among_multiple(self) -> None:
        """When a repo has two agents, each event type routes to the right one."""
        issue_agent = _make_agent("issue-triage", url="http://localhost:8001", event_types=["issue.triage"])
        pr_agent = _make_agent("pr-review", url="http://localhost:8002", event_types=["pr.review"])
        config = _make_config([_make_repo(agents=[issue_agent, pr_agent])])
        router = Router(config)

        issue_result = router.route("issue.triage", "owner/repo")
        pr_result = router.route("pr.review", "owner/repo")

        assert issue_result is not None
        assert issue_result.url == "http://localhost:8001"
        assert pr_result is not None
        assert pr_result.url == "http://localhost:8002"

    def test_unhandled_event_among_multiple_agents_returns_none(self) -> None:
        """If no agent handles the event type, return None even with multiple agents."""
        issue_agent = _make_agent("issue-triage", url="http://localhost:8001")
        config = _make_config([_make_repo(agents=[issue_agent])])
        router = Router(config)

        result = router.route("deployment.created", "owner/repo")

        assert result is None


# ---------------------------------------------------------------------------
# Explicit event_types in config
# ---------------------------------------------------------------------------


class TestExplicitEventTypes:
    """Router uses explicit event_types from agent config when provided."""

    def test_explicit_event_types_takes_priority(self) -> None:
        """Explicit event_types list in config is used for matching."""
        agent = _make_agent(
            "issue-triage",
            url="http://localhost:8001",
            event_types=["issue.triage", "issue.labeled"],
        )
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        assert router.route("issue.triage", "owner/repo") is not None
        assert router.route("issue.labeled", "owner/repo") is not None
        assert router.route("issue.closed", "owner/repo") is None

    def test_prefix_derived_from_agent_type_without_explicit_config(self) -> None:
        """Without explicit event_types, agent type prefix is used (issue-triage → issue.)."""
        agent = _make_agent("issue-triage", url="http://localhost:8001")  # no event_types
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        assert router.route("issue.triage", "owner/repo") is not None
        assert router.route("issue.opened", "owner/repo") is not None
        assert router.route("pull_request.opened", "owner/repo") is None


# ---------------------------------------------------------------------------
# URL registry (register_url)
# ---------------------------------------------------------------------------


class TestRegisterUrl:
    """Router.register_url() allows runtime URL registration for container manager."""

    def test_registered_url_overrides_config_url(self) -> None:
        """A URL registered at runtime takes precedence over the config URL."""
        agent = _make_agent("issue-triage", url="http://config-url:8001")
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        router.register_url("issue-triage", "http://runtime-url:9999")
        result = router.route("issue.triage", "owner/repo")

        assert result is not None
        assert result.url == "http://runtime-url:9999"

    def test_route_uses_config_url_when_registry_empty(self) -> None:
        """When no URL is registered, the config url is used."""
        agent = _make_agent("issue-triage", url="http://config-url:8001")
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        result = router.route("issue.triage", "owner/repo")

        assert result is not None
        assert result.url == "http://config-url:8001"

    def test_agent_without_url_and_no_registry_returns_none(self) -> None:
        """An agent with no url in config and no registered URL returns None."""
        agent = AgentAssignment(type="issue-triage", config={})  # no URL anywhere
        config = _make_config([_make_repo(agents=[agent])])
        router = Router(config)

        result = router.route("issue.triage", "owner/repo")

        assert result is None
