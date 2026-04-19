"""Tests for foreman/__main__.py — startup, entrypoint, and error paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from foreman.__main__ import main

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
        mocker.patch("foreman.__main__.asyncio.run")

        main(["start", "--config", str(config_path)])

        mock_memory_cls.assert_called_once()

    def test_start_runs_asyncio_event_loop(self, tmp_path: Path, mocker) -> None:
        """main() runs the async loop (poller + uvicorn) via asyncio.run."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mock_run = mocker.patch("foreman.__main__.asyncio.run")

        main(["start", "--config", str(config_path)])

        mock_run.assert_called_once()

    def test_start_creates_poller(self, tmp_path: Path, mocker) -> None:
        """main() instantiates a GitHubPoller with the configured token."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mock_poller_cls = mocker.patch("foreman.__main__.GitHubPoller")
        mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.asyncio.run")

        main(["start", "--config", str(config_path)])

        mock_poller_cls.assert_called_once()

    def test_start_creates_dispatcher(self, tmp_path: Path, mocker) -> None:
        """main() instantiates a Dispatcher with config and memory."""
        config_path = tmp_path / "config.yaml"
        _write_minimal_config(config_path)

        mocker.patch("foreman.__main__.MemoryStore")
        mocker.patch("foreman.__main__.GitHubPoller")
        mock_dispatcher_cls = mocker.patch("foreman.__main__.Dispatcher")
        mocker.patch("foreman.__main__.asyncio.run")

        main(["start", "--config", str(config_path)])

        mock_dispatcher_cls.assert_called_once()
