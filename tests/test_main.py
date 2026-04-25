"""Tests for foreman/__main__.py — startup, entrypoint, and error paths."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from foreman.__main__ import _collect_agent_images, _run_loop, main
from foreman.config import load_config
from foreman.containers import ContainerError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_config(path: Path, token: str = "ghp_test") -> None:
    """Write a minimal valid YAML config to *path*."""
    path.write_text(
        f"""
identity:
  github_token: "{token}"
  github_user: "bot"
llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
polling:
  interval_seconds: 60
repos: []
"""
    )


# ---------------------------------------------------------------------------
# CLI error paths
# ---------------------------------------------------------------------------


class TestMainCliErrors:
    """main() exits with a clear message on bad input."""

    def test_missing_config_file_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        """--config pointing to a missing file exits with a non-zero status."""
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--config", str(missing)])
        assert exc_info.value.code != 0

    def test_missing_config_file_prints_error_message(self, tmp_path: Path, capsys) -> None:
        """--config pointing to a missing file prints an error to stderr."""
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(SystemExit):
            main(["start", "--config", str(missing)])
        captured = capsys.readouterr()
        assert "does_not_exist.yaml" in captured.err or "does_not_exist.yaml" in captured.out

    def test_invalid_config_yaml_exits_nonzero(self, tmp_path: Path) -> None:
        """A config file with invalid YAML exits with a non-zero status."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(": invalid: yaml: [")
        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--config", str(bad_yaml)])
        assert exc_info.value.code != 0

    def test_missing_required_field_exits_nonzero(self, tmp_path: Path) -> None:
        """A config missing the 'identity' block exits with a non-zero status."""
        no_identity = tmp_path / "no_identity.yaml"
        no_identity.write_text("llm:\n  provider: anthropic\n  model: x\n")
        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--config", str(no_identity)])
        assert exc_info.value.code != 0

    def test_no_subcommand_exits_nonzero(self) -> None:
        """Calling main() with no arguments exits with a non-zero status."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Startup sequence (mocked)
# ---------------------------------------------------------------------------


class TestMainStartupSequence:
    """main() runs the correct startup sequence with valid config."""

    def test_start_initialises_memory_db(self, tmp_path: Path, mocker) -> None:
        """main() creates a MemoryStore before starting the poller and server."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mock_memory_cls = mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.asyncio.run", side_effect=lambda c: c.close())

        main(["start", "--config", str(config_path)])

        mock_memory_cls.assert_called_once()

    def test_start_runs_asyncio_event_loop(self, tmp_path: Path, mocker) -> None:
        """main() runs the async loop (poller + uvicorn) via asyncio.run."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mock_run = mocker.patch("foreman.__main__.asyncio.run", side_effect=lambda c: c.close())

        main(["start", "--config", str(config_path)])

        mock_run.assert_called_once()

    def test_start_creates_poller(self, tmp_path: Path, mocker) -> None:
        """main() instantiates a GitHubPoller with the configured token."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mock_poller_cls = mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.asyncio.run", side_effect=lambda c: c.close())

        main(["start", "--config", str(config_path)])

        mock_poller_cls.assert_called_once()

    def test_start_creates_dispatcher(self, tmp_path: Path, mocker) -> None:
        """main() instantiates a Dispatcher with config and memory."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mock_dispatcher_cls = mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.asyncio.run", side_effect=lambda c: c.close())

        main(["start", "--config", str(config_path)])

        mock_dispatcher_cls.assert_called_once()


# ---------------------------------------------------------------------------
# Helpers for container-related tests
# ---------------------------------------------------------------------------


def _write_config_with_agent(path: Path) -> None:
    """Write a config with one repo + one agent that has image and port."""
    path.write_text(
        """
identity:
  github_token: "ghp_test"
  github_user: "bot"
llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
repos:
  - owner: "acme"
    name: "widget"
    agents:
      - type: "issue-triage"
        config:
          image: "foreman-issue-triage:latest"
          port: 9001
"""
    )


# ---------------------------------------------------------------------------
# _collect_agent_images
# ---------------------------------------------------------------------------


class TestCollectAgentImages:
    """_collect_agent_images extracts unique (type, image, port) tuples from config."""

    def test_no_repos_returns_empty(self, tmp_path: Path) -> None:
        """Config with no repos yields an empty list."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)
        config = load_config(config_path)

        assert _collect_agent_images(config) == []

    def test_agent_without_image_returns_empty(self, tmp_path: Path) -> None:
        """Agent whose config has no image/port key is not included."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
identity:
  github_token: "ghp_test"
  github_user: "bot"
llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
repos:
  - owner: "acme"
    name: "widget"
    agents:
      - type: "issue-triage"
        config:
          url: "http://localhost:9001"
"""
        )
        config = load_config(config_path)

        assert _collect_agent_images(config) == []

    def test_agent_with_image_and_port_included(self, tmp_path: Path) -> None:
        """Agent with image and port in config is returned as a tuple."""
        config_path = tmp_path / "config.yaml"
        _write_config_with_agent(config_path)
        config = load_config(config_path)

        result = _collect_agent_images(config)

        assert result == [("issue-triage", "foreman-issue-triage:latest", 9001)]

    def test_deduplicates_by_agent_type(self, tmp_path: Path) -> None:
        """Same agent type in multiple repos appears once; first occurrence wins."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            """
identity:
  github_token: "ghp_test"
  github_user: "bot"
llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
repos:
  - owner: "acme"
    name: "widget"
    agents:
      - type: "issue-triage"
        config:
          image: "foreman-issue-triage:latest"
          port: 9001
  - owner: "acme"
    name: "other"
    agents:
      - type: "issue-triage"
        config:
          image: "foreman-issue-triage:other"
          port: 9002
"""
        )
        config = load_config(config_path)

        result = _collect_agent_images(config)

        assert result == [("issue-triage", "foreman-issue-triage:latest", 9001)]


# ---------------------------------------------------------------------------
# Container startup path in main()
# ---------------------------------------------------------------------------


class TestMainContainerStartup:
    """main() starts containers before the async loop when agents have images."""

    def test_no_agent_images_skips_container_manager(self, tmp_path: Path, mocker) -> None:
        """ContainerManager is never instantiated when no agents have image+port."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.asyncio.run", side_effect=lambda c: c.close())
        mock_cm_cls = mocker.patch("foreman.__main__.ContainerManager")

        main(["start", "--config", str(config_path)])

        mock_cm_cls.assert_not_called()

    def test_container_error_at_init_exits_nonzero(self, tmp_path: Path, mocker) -> None:
        """ContainerError from ContainerManager() exits with a non-zero code."""
        config_path = tmp_path / "config.yaml"
        _write_config_with_agent(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.ContainerManager", side_effect=ContainerError("no docker"))

        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--config", str(config_path)])

        assert exc_info.value.code != 0

    def test_container_error_at_init_prints_message(self, tmp_path: Path, mocker, capsys) -> None:
        """ContainerError from ContainerManager() prints an error to stderr."""
        config_path = tmp_path / "config.yaml"
        _write_config_with_agent(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.ContainerManager", side_effect=ContainerError("no docker"))

        with pytest.raises(SystemExit):
            main(["start", "--config", str(config_path)])

        captured = capsys.readouterr()
        assert "no docker" in captured.err

    def test_start_agent_called_with_image_and_port(self, tmp_path: Path, mocker) -> None:
        """start_agent() is called with the image and port from agent config."""
        config_path = tmp_path / "config.yaml"
        _write_config_with_agent(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.asyncio.run", side_effect=lambda c: c.close())
        mock_cm = mocker.MagicMock()
        mock_cm.start_agent.return_value = "http://localhost:9001"
        mocker.patch("foreman.__main__.ContainerManager", return_value=mock_cm)

        main(["start", "--config", str(config_path)])

        mock_cm.start_agent.assert_called_once_with("issue-triage", image="foreman-issue-triage:latest", port=9001)

    def test_start_agent_error_exits_nonzero(self, tmp_path: Path, mocker) -> None:
        """ContainerError from start_agent() exits with a non-zero code."""
        config_path = tmp_path / "config.yaml"
        _write_config_with_agent(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mock_cm = mocker.MagicMock()
        mock_cm.start_agent.side_effect = ContainerError("pull failed")
        mocker.patch("foreman.__main__.ContainerManager", return_value=mock_cm)

        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--config", str(config_path)])

        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# _run_loop container integration
# ---------------------------------------------------------------------------


class TestRunLoopContainerLifecycle:
    """_run_loop registers container URLs with the router and stops on shutdown."""

    def _make_fast_run_loop(self, tmp_path: Path, mocker, container_manager=None, agent_urls=None):
        """Return args for _run_loop with a mocked poller + uvicorn that exit immediately."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)
        config = load_config(config_path)

        mock_memory = mocker.MagicMock()
        mock_poller = mocker.MagicMock()
        mock_poller.run = mocker.AsyncMock()
        mock_dispatcher = mocker.MagicMock()

        mock_server = mocker.MagicMock()
        mock_server.serve = mocker.AsyncMock()
        mocker.patch("uvicorn.Server", return_value=mock_server)
        mocker.patch("uvicorn.Config")

        return config, mock_memory, mock_poller, mock_dispatcher

    def test_register_url_called_for_each_agent(self, tmp_path: Path, mocker) -> None:
        """agent_urls entries are registered with the router before the poll loop."""
        config, memory, poller, dispatcher = self._make_fast_run_loop(tmp_path, mocker)

        mock_router_cls = mocker.patch("foreman.__main__.Router")
        mock_router = mock_router_cls.return_value

        agent_urls = {"issue-triage": "http://localhost:9001"}

        asyncio.run(_run_loop(config, memory, poller, dispatcher, "0.0.0.0", 8000, None, agent_urls))

        mock_router.register_url.assert_called_once_with("issue-triage", "http://localhost:9001")

    def test_no_agent_urls_no_register_call(self, tmp_path: Path, mocker) -> None:
        """When agent_urls is empty, register_url is never called."""
        config, memory, poller, dispatcher = self._make_fast_run_loop(tmp_path, mocker)

        mock_router_cls = mocker.patch("foreman.__main__.Router")
        mock_router = mock_router_cls.return_value

        asyncio.run(_run_loop(config, memory, poller, dispatcher, "0.0.0.0", 8000, None, {}))

        mock_router.register_url.assert_not_called()

    def test_stop_all_called_on_shutdown(self, tmp_path: Path, mocker) -> None:
        """container_manager.stop_all() is called when the server loop exits."""
        config, memory, poller, dispatcher = self._make_fast_run_loop(tmp_path, mocker)
        mocker.patch("foreman.__main__.Router")

        mock_cm = mocker.MagicMock()

        asyncio.run(_run_loop(config, memory, poller, dispatcher, "0.0.0.0", 8000, mock_cm, {}))

        mock_cm.stop_all.assert_called_once()

    def test_no_container_manager_no_stop_call(self, tmp_path: Path, mocker) -> None:
        """When container_manager is None, no stop call is attempted."""
        config, memory, poller, dispatcher = self._make_fast_run_loop(tmp_path, mocker)
        mocker.patch("foreman.__main__.Router")

        # Should not raise even with container_manager=None
        asyncio.run(_run_loop(config, memory, poller, dispatcher, "0.0.0.0", 8000, None, {}))
