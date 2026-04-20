"""Tests for foreman.containers — Docker container lifecycle manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from foreman.containers import ContainerError, ContainerManager


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _mock_docker_client(images_present: bool = True):
    """Return a patched docker.from_env() client."""
    client = MagicMock()
    # images.get raises ImageNotFound when not present
    if images_present:
        client.images.get.return_value = MagicMock()
    else:
        import docker.errors

        client.images.get.side_effect = docker.errors.ImageNotFound("not found")
    # images.pull succeeds silently
    client.images.pull.return_value = MagicMock()
    return client


# ---------------------------------------------------------------------------
# ContainerManager.__init__ — Docker socket availability
# ---------------------------------------------------------------------------


class TestContainerManagerInit:
    """ContainerManager raises ContainerError when Docker is unavailable."""

    def test_raises_container_error_when_docker_unavailable(self, mocker):
        """ContainerError is raised if the Docker socket is not reachable."""
        import docker.errors

        mocker.patch("docker.from_env", side_effect=docker.errors.DockerException("socket not found"))
        with pytest.raises(ContainerError, match="Docker"):
            ContainerManager()

    def test_initialises_when_docker_available(self, mocker):
        """ContainerManager initialises without error when Docker is reachable."""
        client = MagicMock()
        mocker.patch("docker.from_env", return_value=client)
        mgr = ContainerManager()
        assert mgr is not None


# ---------------------------------------------------------------------------
# start_agent — image pulling
# ---------------------------------------------------------------------------


class TestStartAgentImageHandling:
    """start_agent pulls the image if it is not present locally."""

    def test_pulls_image_when_not_present(self, mocker):
        """Image is pulled when not found in the local registry."""
        import docker.errors

        client = MagicMock()
        client.images.get.side_effect = docker.errors.ImageNotFound("not found")
        client.images.pull.return_value = MagicMock()
        container = MagicMock()
        container.id = "abc123"
        container.status = "running"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)

        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        client.images.pull.assert_called_once_with("foreman-issue-triage:latest")

    def test_skips_pull_when_image_present(self, mocker):
        """Image pull is skipped when the image exists locally."""
        client = _mock_docker_client(images_present=True)
        container = MagicMock()
        container.id = "abc123"
        container.status = "running"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)

        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        client.images.pull.assert_not_called()


# ---------------------------------------------------------------------------
# start_agent — container startup and URL return
# ---------------------------------------------------------------------------


class TestStartAgentContainer:
    """start_agent returns the container URL and registers it internally."""

    def test_returns_container_url(self, mocker):
        """start_agent returns the http://localhost:<port> URL."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)

        url = mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        assert url == "http://localhost:9001"

    def test_container_registered_internally(self, mocker):
        """The started container is tracked so stop_all can clean it up."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)

        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        assert "issue-triage" in mgr._containers

    def test_waits_for_health_before_returning(self, mocker):
        """_wait_for_health is called with the container URL."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        wait_mock = mocker.patch.object(mgr, "_wait_for_health")

        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        wait_mock.assert_called_once_with("http://localhost:9001")


# ---------------------------------------------------------------------------
# stop_all
# ---------------------------------------------------------------------------


class TestStopAll:
    """stop_all stops and removes all managed containers."""

    def test_stops_all_managed_containers(self, mocker):
        """stop_all calls stop() on every tracked container."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)
        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        mgr.stop_all()

        container.stop.assert_called_once()

    def test_stop_all_is_idempotent(self, mocker):
        """Calling stop_all twice does not raise an error."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)
        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        mgr.stop_all()
        mgr.stop_all()  # should not raise

    def test_stop_all_clears_registry(self, mocker):
        """After stop_all, _containers is empty."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)
        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        mgr.stop_all()

        assert mgr._containers == {}


# ---------------------------------------------------------------------------
# _wait_for_health — health polling
# ---------------------------------------------------------------------------


class TestWaitForHealth:
    """_wait_for_health polls /health until the container responds."""

    def test_returns_immediately_when_healthy(self, mocker):
        """No retry when /health returns 200 on first attempt."""
        client = MagicMock()
        mocker.patch("docker.from_env", return_value=client)

        import httpx

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mocker.patch("httpx.get", return_value=mock_response)

        mgr = ContainerManager()
        mgr._wait_for_health("http://localhost:9001")  # should not raise

    def test_raises_container_error_when_never_healthy(self, mocker):
        """ContainerError is raised when /health never responds within timeout."""
        client = MagicMock()
        mocker.patch("docker.from_env", return_value=client)
        mocker.patch("httpx.get", side_effect=Exception("connection refused"))
        mocker.patch("time.sleep")  # don't actually sleep in tests

        mgr = ContainerManager()
        with pytest.raises(ContainerError, match="health"):
            mgr._wait_for_health("http://localhost:9001", retries=2, delay=0)


# ---------------------------------------------------------------------------
# Unexpected container exit — restart logic
# ---------------------------------------------------------------------------


class TestContainerRestartOnExit:
    """Unexpected container exit triggers one restart attempt."""

    def test_logs_error_and_restarts_once_on_exit(self, mocker):
        """When a container exits unexpectedly, it is restarted once."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)
        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        mock_logger = mocker.patch("foreman.containers.logger")

        mgr.handle_container_exit("issue-triage", image="foreman-issue-triage:latest", port=9001)

        mock_logger.error.assert_called_once()
        # Restart means containers.run was called again (second call)
        assert client.containers.run.call_count == 2

    def test_marks_failed_after_second_exit(self, mocker):
        """If the restarted container exits again, it is marked failed (no further restarts)."""
        client = _mock_docker_client()
        container = MagicMock()
        container.id = "abc123"
        client.containers.run.return_value = container
        mocker.patch("docker.from_env", return_value=client)

        mgr = ContainerManager()
        mocker.patch.object(mgr, "_wait_for_health", return_value=None)
        mgr.start_agent("issue-triage", image="foreman-issue-triage:latest", port=9001)

        mocker.patch("foreman.containers.logger")

        # First exit → restart
        mgr.handle_container_exit("issue-triage", image="foreman-issue-triage:latest", port=9001)
        # Second exit → mark failed, no further restart
        mgr.handle_container_exit("issue-triage", image="foreman-issue-triage:latest", port=9001)

        assert client.containers.run.call_count == 2  # no third start
        assert mgr._failed == {"issue-triage"}
