"""Docker container lifecycle management for agent containers."""

from __future__ import annotations

import time

import docker
import docker.errors
import docker.models.containers
import httpx
import structlog

logger = structlog.get_logger(__name__)


class ContainerError(Exception):
    """Raised when a container operation fails."""


class ContainerManager:
    """Manages Docker container start/stop for configured agent types.

    On startup, pull (if needed) and start agent containers.  On shutdown,
    call :meth:`stop_all` to stop them.  The container lifecycle manager
    registers URLs with the router after each successful start.

    Raises:
        ContainerError: If the Docker socket is unavailable at construction time.
    """

    def __init__(self) -> None:
        try:
            self._client = docker.from_env()
        except docker.errors.DockerException as exc:
            raise ContainerError(f"Docker socket unavailable — is Docker running? ({exc})") from exc

        # agent_type → docker container object
        self._containers: dict[str, docker.models.containers.Container] = {}
        # agent types that have permanently failed (after one restart attempt)
        self._failed: set[str] = set()
        # track restart attempts per agent_type
        self._restart_attempts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_agent(self, agent_type: str, *, image: str, port: int) -> str:
        """Pull (if needed), start the container, wait for health, return URL.

        Args:
            agent_type: Agent type identifier (e.g. ``"issue-triage"``).
            image: Docker image name/tag to run.
            port: Host port to bind the container's port 8000 to.

        Returns:
            The base URL of the running container (e.g. ``"http://localhost:9001"``).

        Raises:
            ContainerError: If the container fails to become healthy.
        """
        self._ensure_image(image)
        container = self._client.containers.run(
            image,
            detach=True,
            ports={"8000/tcp": port},
            name=f"foreman-{agent_type}",
            remove=True,
        )
        self._containers[agent_type] = container
        self._restart_attempts[agent_type] = 0

        url = f"http://localhost:{port}"
        self._wait_for_health(url)
        logger.info("Agent container started", agent_type=agent_type, url=url)
        return url

    def stop_all(self) -> None:
        """Stop all managed containers.

        Safe to call multiple times.
        """
        for agent_type, container in list(self._containers.items()):
            try:
                container.stop()
                logger.info("Agent container stopped", agent_type=agent_type)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping container", agent_type=agent_type, error=str(exc))
        self._containers = {}

    def handle_container_exit(self, agent_type: str, *, image: str, port: int) -> None:
        """Handle an unexpected container exit with one restart attempt.

        If the container has already been restarted once and exits again, it is
        marked as permanently failed and no further restart is attempted.

        Args:
            agent_type: Agent type identifier.
            image: Docker image to restart.
            port: Host port for the restarted container.
        """
        if agent_type in self._failed:
            logger.critical("Agent already marked failed — not restarting", agent_type=agent_type)
            return

        attempts = self._restart_attempts.get(agent_type, 0)
        if attempts >= 1:
            logger.critical(
                "Agent container exited after restart — marking failed",
                agent_type=agent_type,
            )
            self._failed.add(agent_type)
            self._containers.pop(agent_type, None)
            return

        logger.error("Agent container exited unexpectedly — attempting restart", agent_type=agent_type)
        self._restart_attempts[agent_type] = attempts + 1

        self._ensure_image(image)
        container = self._client.containers.run(
            image,
            detach=True,
            ports={"8000/tcp": port},
            name=f"foreman-{agent_type}",
            remove=True,
        )
        self._containers[agent_type] = container

        url = f"http://localhost:{port}"
        try:
            self._wait_for_health(url)
        except ContainerError:
            logger.critical("Restarted container failed health check — marking failed", agent_type=agent_type)
            self._failed.add(agent_type)
            return

        logger.info("Agent container restarted successfully", agent_type=agent_type, url=url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_image(self, image: str) -> None:
        """Pull *image* if it is not present in the local Docker registry.

        Args:
            image: Docker image name/tag.
        """
        try:
            self._client.images.get(image)
        except docker.errors.ImageNotFound:
            logger.info("Pulling image", image=image)
            self._client.images.pull(image)

    def _wait_for_health(self, url: str, *, retries: int = 30, delay: float = 1.0) -> None:
        """Poll *url*/health until a 200 response is received.

        Args:
            url: Base URL of the container (e.g. ``"http://localhost:9001"``).
            retries: Maximum number of attempts before raising.
            delay: Seconds to wait between attempts.

        Raises:
            ContainerError: If the health endpoint does not respond within *retries* attempts.
        """
        health_url = f"{url}/health"
        for attempt in range(retries):
            try:
                response = httpx.get(health_url, timeout=2.0)
                if response.status_code == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                logger.debug("Health check attempt failed", url=health_url, attempt=attempt, error=str(exc))
            if attempt < retries - 1:
                time.sleep(delay)

        raise ContainerError(f"Container at {url} did not pass health check after {retries} attempts")
