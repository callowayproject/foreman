"""Night Brownie CLI entrypoint.

Usage:

    night-brownie start --config config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import uvicorn

from night_brownie.config import ConfigError, load_config
from night_brownie.containers import ContainerError, ContainerManager
from night_brownie.memory import MemoryStore
from night_brownie.poller import GitHubPoller
from night_brownie.queue import TaskQueue
from night_brownie.routers import Router, RoutingError
from night_brownie.server import Dispatcher, app

if TYPE_CHECKING:
    from night_brownie.config import NightBrownieConfig, RepoConfig

logger = structlog.get_logger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".night-brownie" / "memory.db"
"""Default memory DB path."""

_DEFAULT_QUEUE_DB_PATH = Path.home() / ".night-brownie" / "queue.db"
"""Default queue DB path."""


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the Night Brownie CLI.

    Returns:
        Configured `argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="night-brownie",
        description="Night Brownie — AI OSS co-maintainer harness",
    )
    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser("start", help="Start the Night Brownie harness")
    start.add_argument(
        "--config",
        required=True,
        metavar="CONFIG",
        help="Path to the YAML configuration file",
    )
    start.add_argument(
        "--db",
        default=str(_DEFAULT_DB_PATH),
        metavar="DB_PATH",
        help="Path to the SQLite memory database (default: ~/.night-brownie/memory.db)",
    )
    start.add_argument(
        "--queue-db",
        default=None,
        metavar="QUEUE_DB_PATH",
        help="Path to the SQLite task queue database (default: ~/.night-brownie/queue.db)",
    )
    start.add_argument(
        "--host",
        default="0.0.0.0",
        metavar="HOST",
        help="Host to bind the HTTP server to (default: 0.0.0.0)",
    )
    start.add_argument(
        "--port",
        type=int,
        default=8000,
        metavar="PORT",
        help="Port for the HTTP server (default: 8000)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and run Night Brownie.

    Args:
        argv: Argument list (defaults to `sys.argv[1:]` when `None`).

    Raises:
        SystemExit: On invalid arguments or configuration errors.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(2)

    if args.command == "start":
        _run_start(args)


def _collect_agent_images(config: NightBrownieConfig) -> list[tuple[str, str, int]]:
    """Collect unique `(agent_type, image, port)` specs from the config.

    Only includes agents that have both `image` and `port` in their
    `config` dict.  Deduplicates by agent type — if the same agent type
    appears in multiple repos, the first occurrence wins.

    Args:
        config: Validated `night_brownie.config.NightBrownieConfig`.

    Returns:
        List of `(agent_type, image, port)` tuples, deduplicated by agent type.
    """
    seen: set[str] = set()
    specs: list[tuple[str, str, int]] = []
    for repo in config.repos:
        for agent in repo.agents:
            if agent.type in seen:
                continue
            image = agent.config.get("image")
            port = agent.config.get("port")
            if image and port:
                seen.add(agent.type)
                specs.append((agent.type, str(image), int(port)))
    return specs


def _run_start(args: Any) -> None:
    """Execute the `start` sub-command.

    Validates config, initializes the memory DB, then runs the poller and
    HTTP server concurrently inside a single asyncio event loop.

    Args:
        args: Parsed namespace from argparse.

    Raises:
        SystemExit: On config validation failure.
    """
    # 1. Load and validate config — fail fast with a clear message.
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Initialize memory DB.
    db_path = Path(args.db)
    memory = MemoryStore(db_path)

    # 3. Create core components.
    if args.queue_db is not None:
        queue_db_path = Path(args.queue_db)
    elif config.queue.db_path is not None:
        queue_db_path = config.queue.db_path
    else:
        queue_db_path = _DEFAULT_QUEUE_DB_PATH
    with TaskQueue(queue_db_path, claim_timeout_seconds=config.queue.claim_timeout_seconds) as task_queue:
        dispatcher = Dispatcher(config=config, memory=memory, task_queue=task_queue)

        # Expose shared state for the lifespan background loops.
        app.state.task_queue = task_queue
        app.state.executor = dispatcher.executor
        app.state.memory = memory
        app.state.config = config

        poller = GitHubPoller(token=config.identity.github_token, memory=memory)

        # 4. Start agent containers (if any are configured with image + port).
        container_manager: ContainerManager | None = None
        agent_urls: dict[str, str] = {}
        agent_specs = _collect_agent_images(config)

        if agent_specs:
            try:
                container_manager = ContainerManager()
            except ContainerError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
            for agent_type, image, port in agent_specs:
                try:
                    url = container_manager.start_agent(agent_type, image=image, port=port)
                    agent_urls[agent_type] = url
                except ContainerError as exc:
                    print(f"Error starting agent '{agent_type}': {exc}", file=sys.stderr)
                    sys.exit(1)

        logger.info(
            "Night Brownie initialized",
            config=args.config,
            db=str(db_path),
            repos=[f"{r.owner}/{r.name}" for r in config.repos],
            poll_interval_seconds=config.polling.interval_seconds,
        )

        # 5. Run the poller and HTTP server concurrently.
        asyncio.run(_run_loop(config, memory, poller, dispatcher, args.host, args.port, container_manager, agent_urls))


async def _run_loop(
    config: NightBrownieConfig,
    memory: MemoryStore,
    poller: GitHubPoller,
    dispatcher: Dispatcher,
    host: str,
    port: int,
    container_manager: ContainerManager | None = None,
    agent_urls: dict[str, str] | None = None,
) -> None:
    """Run the poll loop and HTTP server concurrently.

    The poller is started as an asyncio task alongside the uvicorn server.
    On shutdown (SIGINT/SIGTERM), the poller task is cancelled cleanly and
    any managed containers are stopped.

    Args:
        config: Validated runtime configuration.
        memory: Open memory store (passed through for context).
        poller: Initialized `night_brownie.poller.GitHubPoller`.
        dispatcher: Initialized `night_brownie.server.Dispatcher`.
        host: Bind address for the HTTP server.
        port: Port for the HTTP server.
        container_manager: Optional `night_brownie.containers.ContainerManager`
            to stop on shutdown.
        agent_urls: Mapping of agent type → base URL for pre-started containers.
            Each entry is registered with the router before polling begins.
    """
    router = Router(config)

    for agent_type, url in (agent_urls or {}).items():
        router.register_url(agent_type, url)

    async def on_event(repo_config: RepoConfig, event: dict[str, Any]) -> None:
        """Handle one poller event: route it and dispatch to the appropriate agent.

        Args:
            repo_config: The repo configuration that produced this event.
            event: Event dict with `repo`, `issue_number`, and `payload`.
        """
        repo = event["repo"]
        issue_number = event["issue_number"]
        logger.info("Issue event", repo=repo, issue_number=issue_number)
        try:
            route_target = router.route("issue.triage", repo)
        except RoutingError:
            logger.warning("Repo not in config — skipping", repo=repo)
            return
        if route_target is None:
            logger.debug("No agent handles issue.triage for this repo", repo=repo)
            return
        logger.info(
            "Routing to agent",
            repo=repo,
            issue_number=issue_number,
            agent_url=route_target.url,
        )
        await dispatcher.dispatch(event, route_target)

    uv_server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None))

    logger.info(
        "Night Brownie started — polling every %d seconds, server on %s:%d",
        config.polling.interval_seconds,
        host,
        port,
    )

    poller_task = asyncio.create_task(poller.run(config.repos, config.polling.interval_seconds, on_event))

    def _on_poller_done(task: asyncio.Task) -> None:
        """Log unexpected poller task termination."""
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.critical("Poller task crashed unexpectedly", exc_info=exc)

    poller_task.add_done_callback(_on_poller_done)

    try:
        await uv_server.serve()
    finally:
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            logger.info("Poller stopped cleanly")
        if container_manager is not None:
            container_manager.stop_all()


if __name__ == "__main__":
    main()
