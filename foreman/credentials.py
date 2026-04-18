"""Credential injection and environment variable resolution.

Secrets are stored exclusively in environment variables and resolved at
runtime via ``${VAR}`` references.  No credential value is ever written to
logs or exposed in exception messages beyond the variable name.
"""

from __future__ import annotations

import os
import re

_ENV_REF_RE = re.compile(r"\$\{([^}]+)\}")


class CredentialError(Exception):
    """Raised when a required credential or env var is missing."""


def resolve_env_refs(value: str) -> str:
    """Substitute all ``${VAR}`` patterns with their environment variable values.

    Args:
        value: A string potentially containing ``${VAR}`` references.

    Returns:
        The string with every reference replaced by the corresponding
        environment variable value.

    Raises:
        CredentialError: If any referenced variable is absent from the
            environment.  The message names the missing variable but never
            includes surrounding literal text or any resolved values.
    """

    def _replace(match: re.Match) -> str:
        var = match.group(1)
        resolved = os.environ.get(var)
        if resolved is None:
            raise CredentialError(f"Required environment variable '{var}' is not set")
        return resolved

    return _ENV_REF_RE.sub(_replace, value)


def get_github_token() -> str:
    """Return the GitHub Personal Access Token from the environment.

    Returns:
        The value of the ``GITHUB_TOKEN`` environment variable.

    Raises:
        CredentialError: If ``GITHUB_TOKEN`` is not set in the environment.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if token is None:
        raise CredentialError("Required environment variable 'GITHUB_TOKEN' is not set")
    return token
