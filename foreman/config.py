"""YAML config loader and Pydantic validation for Foreman.

All secrets are ${VAR} environment variable references — the config file
itself never contains raw secret values.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator

_ENV_REF_RE = re.compile(r"\$\{([^}]+)\}")


class ConfigError(Exception):
    """Raised when config loading or validation fails."""


# ---------------------------------------------------------------------------
# Environment variable resolution
# ---------------------------------------------------------------------------


def _resolve_env_refs(value: str) -> str:
    """Substitute all ``${VAR}`` patterns with their environment values.

    Args:
        value: A string that may contain one or more ``${VAR}`` references.

    Returns:
        The string with all references substituted.

    Raises:
        ConfigError: If any referenced variable is not set in the environment.
    """

    def _replace(match: re.Match) -> str:
        var = match.group(1)
        resolved = os.environ.get(var)
        if resolved is None:
            raise ConfigError(f"Environment variable '{var}' is not set")
        return resolved

    return _ENV_REF_RE.sub(_replace, value)


def _resolve_refs_in(obj: Any) -> Any:
    """Recursively resolve ``${VAR}`` references in dicts, lists, and strings.

    Args:
        obj: A nested structure (dict, list, str, or other).

    Returns:
        The same structure with all string ``${VAR}`` references substituted.
    """
    if isinstance(obj, str):
        return _resolve_env_refs(obj)
    if isinstance(obj, dict):
        return {k: _resolve_refs_in(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_refs_in(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Secret-masking string type
# ---------------------------------------------------------------------------


class _SecretStr(str):
    """A string subclass that masks its value in repr and str output."""

    def __repr__(self) -> str:
        """Return masked representation."""
        return "'**********'"

    def __str__(self) -> str:
        """Return masked string value."""
        return "**********"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class IdentityConfig(BaseModel):
    """Bot GitHub identity configuration."""

    github_token: str
    """GitHub Personal Access Token for the bot account."""

    github_user: str
    """GitHub username of the bot account."""

    @field_validator("github_token", mode="after")
    @classmethod
    def mask_token(cls, v: str) -> str:
        """Wrap the token in a secret-masking string."""
        return _SecretStr(v)


class LLMConfig(BaseModel):
    """LLM backend configuration."""

    provider: str
    """LLM provider identifier (e.g. ``anthropic``, ``ollama``)."""

    model: str
    """Model name / identifier."""

    api_key: Optional[str] = None
    """API key; omit for local providers such as Ollama."""

    @field_validator("api_key", mode="after")
    @classmethod
    def mask_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Wrap the API key in a secret-masking string if present."""
        return _SecretStr(v) if v is not None else None


class PollingConfig(BaseModel):
    """GitHub polling configuration."""

    interval_seconds: int = 60
    """How often to poll GitHub for new events (in seconds)."""


class AgentAssignment(BaseModel):
    """A single agent assigned to a repository."""

    type: str
    """Agent type identifier (e.g. ``issue-triage``)."""

    config: dict[str, Any] = {}
    """Agent-specific configuration options."""

    allow_close: bool = False
    """Whether this agent may close issues."""


class RepoConfig(BaseModel):
    """Configuration for a single repository."""

    owner: str
    """Repository owner (user or organization)."""

    name: str
    """Repository name."""

    agents: list[AgentAssignment] = []
    """Agents assigned to this repository."""


class ForemanConfig(BaseModel):
    """Top-level Foreman runtime configuration."""

    identity: IdentityConfig
    """Bot GitHub identity."""

    llm: LLMConfig
    """LLM backend configuration."""

    polling: PollingConfig = PollingConfig()
    """GitHub polling settings."""

    repos: list[RepoConfig] = []
    """Repositories to monitor."""

    @model_validator(mode="before")
    @classmethod
    def _check_required(cls, data: Any) -> Any:
        """Fail fast when mandatory top-level sections are absent."""
        if isinstance(data, dict) and "identity" not in data:
            raise ValueError("missing required field: 'identity'")
        return data


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path: Path | str) -> ForemanConfig:
    """Load and validate a Foreman YAML configuration file.

    Resolves ``${VAR}`` environment variable references before validation.
    Fails fast with a :class:`ConfigError` if the file is missing, the YAML
    is malformed, a required field is absent, or a referenced environment
    variable is not set.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A validated :class:`ForemanConfig` instance.

    Raises:
        ConfigError: If anything goes wrong during loading or validation.
    """
    path = Path(path)

    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config file must be a YAML mapping, got {type(raw).__name__}")

    try:
        resolved = _resolve_refs_in(raw)
    except ConfigError:
        raise

    from pydantic import ValidationError

    try:
        return ForemanConfig.model_validate(resolved)
    except ValidationError as exc:
        # Surface the first missing/invalid field name clearly.
        first = exc.errors()[0]
        loc = " -> ".join(str(p) for p in first["loc"]) if first["loc"] else "unknown"
        raise ConfigError(f"Config validation error at '{loc}': {first['msg']}") from exc
