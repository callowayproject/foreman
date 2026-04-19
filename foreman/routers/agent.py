"""Routes GitHub events (repo + event_type) to configured agent URLs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from foreman.config import AgentAssignment, ForemanConfig

logger = structlog.get_logger(__name__)


class RoutingError(Exception):
    """Raised when a repo is not found in the Foreman config."""


@dataclass
class RouteTarget:
    """The resolved destination for a routed event.

    Attributes:
        url: HTTP base URL of the agent container's ``/task`` endpoint.
        agent_assignment: The matching :class:`~foreman.config.AgentAssignment`
            (includes ``allow_close`` and agent-specific config).
    """

    url: str
    agent_assignment: AgentAssignment


def _derives_event_prefix(agent_type: str) -> str:
    """Derive the event-type prefix from the agent type name.

    Examples::

        "issue-triage"  → "issue."
        "pr-review"     → "pr."

    Args:
        agent_type: The agent type identifier (e.g. ``"issue-triage"``).

    Returns:
        The event-type prefix string (e.g. ``"issue."``).
    """
    return agent_type.split("-", maxsplit=1)[0] + "."


def _agent_handles_event(agent: AgentAssignment, event_type: str) -> bool:
    """Return True if *agent* should handle *event_type*.

    Uses the explicit ``event_types`` list from the agent config when present;
    otherwise falls back to a prefix derived from the agent type.

    Args:
        agent: The agent assignment to check.
        event_type: The event type string (e.g. ``"issue.triage"``).

    Returns:
        ``True`` if the agent handles this event type.
    """
    if "event_types" in agent.config:
        return event_type in agent.config["event_types"]
    prefix = _derives_event_prefix(agent.type)
    return event_type.startswith(prefix)


class Router:
    """Maps GitHub events to agent URLs based on the Foreman config.

    Initialised once at startup with the parsed config.  The container
    lifecycle manager calls :meth:`register_url` after each agent container
    starts so that dynamically-assigned ports are used at dispatch time.

    Args:
        config: Validated :class:`~foreman.config.ForemanConfig`.
    """

    def __init__(self, config: ForemanConfig) -> None:
        self._config = config
        self._url_registry: dict[str, str] = {}

    def register_url(self, agent_type: str, url: str) -> None:
        """Register a runtime URL for *agent_type*.

        Overrides any ``url`` value from the YAML config.  Called by the
        container lifecycle manager after a container is started.

        Args:
            agent_type: Agent type identifier (e.g. ``"issue-triage"``).
            url: Base URL of the running container (e.g. ``"http://localhost:9001"``).
        """
        self._url_registry[agent_type] = url

    def route(self, event_type: str, repo: str) -> RouteTarget | None:
        """Return the :class:`RouteTarget` for *event_type* in *repo*, or ``None``.

        Args:
            event_type: GitHub event type string (e.g. ``"issue.triage"``).
            repo: Repository in ``owner/repo`` format.

        Returns:
            A :class:`RouteTarget` when a matching agent with a known URL is
            found, or ``None`` when no agent handles this event type.

        Raises:
            RoutingError: When *repo* is not present in the config.
        """
        repo_config = next(
            (r for r in self._config.repos if f"{r.owner}/{r.name}" == repo),
            None,
        )
        if repo_config is None:
            raise RoutingError(f"No configuration found for repo: {repo}")

        for agent in repo_config.agents:
            if not _agent_handles_event(agent, event_type):
                continue
            url = self._url_registry.get(agent.type) or agent.config.get("url")
            if url is None:
                logger.warning(
                    "Agent has no URL — skipping",
                    agent_type=agent.type,
                    repo=repo,
                    event_type=event_type,
                )
                continue
            return RouteTarget(url=url, agent_assignment=agent)

        return None
