"""Tests for foreman/config.py."""

import textwrap
from pathlib import Path

import pytest

from foreman.config import ConfigError, ForemanConfig, load_config


VALID_YAML = textwrap.dedent("""\
    identity:
      github_token: "ghp_test_token"
      github_user: "test-bot"

    llm:
      provider: anthropic
      model: claude-sonnet-4-6
      api_key: "sk-ant-test"

    polling:
      interval_seconds: 60

    repos:
      - owner: my-org
        name: my-repo
        agents:
          - type: issue-triage
            config:
              stale_days: 30
              labels:
                bug: ["crash", "exception"]
""")

YAML_WITH_ENV_REFS = textwrap.dedent("""\
    identity:
      github_token: "${GITHUB_TOKEN}"
      github_user: "test-bot"

    llm:
      provider: anthropic
      model: claude-sonnet-4-6
      api_key: "${ANTHROPIC_API_KEY}"

    polling:
      interval_seconds: 60

    repos:
      - owner: my-org
        name: my-repo
        agents:
          - type: issue-triage
""")


@pytest.fixture()
def valid_config_file(tmp_path: Path) -> Path:
    """Write a valid config YAML file and return its path."""
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML)
    return p


@pytest.fixture()
def env_ref_config_file(tmp_path: Path) -> Path:
    """Write a config YAML file with ${VAR} env refs and return its path."""
    p = tmp_path / "config.yaml"
    p.write_text(YAML_WITH_ENV_REFS)
    return p


class TestLoadConfig:
    """Tests for load_config()."""

    def test_valid_yaml_loads_without_error(self, valid_config_file: Path) -> None:
        """A well-formed config file loads and returns a ForemanConfig instance."""
        config = load_config(valid_config_file)
        assert isinstance(config, ForemanConfig)

    def test_returns_correct_identity(self, valid_config_file: Path) -> None:
        """Loaded config contains expected identity values."""
        config = load_config(valid_config_file)
        assert config.identity.github_user == "test-bot"
        assert config.identity.github_token == "ghp_test_token"

    def test_returns_correct_llm_config(self, valid_config_file: Path) -> None:
        """Loaded config contains expected LLM values."""
        config = load_config(valid_config_file)
        assert config.llm.provider == "anthropic"
        assert config.llm.model == "claude-sonnet-4-6"

    def test_returns_correct_polling_interval(self, valid_config_file: Path) -> None:
        """Loaded config contains correct polling interval."""
        config = load_config(valid_config_file)
        assert config.polling.interval_seconds == 60

    def test_returns_correct_repos(self, valid_config_file: Path) -> None:
        """Loaded config contains correct repo list."""
        config = load_config(valid_config_file)
        assert len(config.repos) == 1
        assert config.repos[0].owner == "my-org"
        assert config.repos[0].name == "my-repo"

    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        """Loading a non-existent file raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_missing_required_field_raises_config_error(self, tmp_path: Path) -> None:
        """Missing required field raises ConfigError with the field name."""
        bad_yaml = textwrap.dedent("""\
            llm:
              provider: anthropic
              model: claude-sonnet-4-6
            polling:
              interval_seconds: 60
            repos: []
        """)
        p = tmp_path / "config.yaml"
        p.write_text(bad_yaml)
        with pytest.raises(ConfigError, match="identity"):
            load_config(p)

    def test_invalid_yaml_raises_config_error(self, tmp_path: Path) -> None:
        """Malformed YAML raises ConfigError."""
        p = tmp_path / "config.yaml"
        p.write_text(":: invalid: yaml: [\n")
        with pytest.raises(ConfigError):
            load_config(p)


class TestEnvVarResolution:
    """Tests for ${VAR} environment variable resolution."""

    def test_env_refs_resolved_from_environment(
        self, env_ref_config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """${VAR} references are substituted from environment variables."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
        config = load_config(env_ref_config_file)
        assert config.identity.github_token == "ghp_from_env"
        assert config.llm.api_key == "sk-from-env"

    def test_missing_env_var_raises_config_error(
        self, env_ref_config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing env var for a ${VAR} reference raises ConfigError with the var name."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
            load_config(env_ref_config_file)


class TestConfigRepr:
    """Tests that secrets do not leak into repr/str output."""

    def test_repr_does_not_contain_github_token(self, valid_config_file: Path) -> None:
        """repr() of ForemanConfig must not contain the github_token value."""
        config = load_config(valid_config_file)
        assert "ghp_test_token" not in repr(config)

    def test_repr_does_not_contain_api_key(self, valid_config_file: Path) -> None:
        """repr() of ForemanConfig must not contain the api_key value."""
        config = load_config(valid_config_file)
        assert "sk-ant-test" not in repr(config)
