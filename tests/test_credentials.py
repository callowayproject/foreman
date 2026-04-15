"""Tests for foreman/credentials.py."""

import pytest

from foreman.credentials import CredentialError, get_github_token, resolve_env_refs


class TestResolveEnvRefs:
    """Tests for resolve_env_refs()."""

    def test_single_ref_substituted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A single ${VAR} reference is resolved from the environment."""
        monkeypatch.setenv("MY_TOKEN", "abc123")
        assert resolve_env_refs("${MY_TOKEN}") == "abc123"

    def test_multiple_refs_substituted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple ${VAR} references in one string are all resolved."""
        monkeypatch.setenv("FIRST", "hello")
        monkeypatch.setenv("SECOND", "world")
        assert resolve_env_refs("${FIRST} ${SECOND}") == "hello world"

    def test_literal_string_unchanged(self) -> None:
        """A string with no ${VAR} references is returned unchanged."""
        assert resolve_env_refs("plain_value") == "plain_value"

    def test_missing_env_var_raises_credential_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing env var raises CredentialError with the variable name in the message."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(CredentialError, match="MISSING_VAR"):
            resolve_env_refs("${MISSING_VAR}")

    def test_error_message_does_not_contain_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CredentialError message does not contain the resolved value."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        try:
            resolve_env_refs("prefix_${SECRET_KEY}_suffix")
        except CredentialError as exc:
            assert "prefix_" not in str(exc)
            assert "_suffix" not in str(exc)


class TestGetGithubToken:
    """Tests for get_github_token()."""

    def test_returns_token_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_github_token() returns the GITHUB_TOKEN env var value."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        assert get_github_token() == "ghp_test123"

    def test_missing_token_raises_credential_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_github_token() raises CredentialError when GITHUB_TOKEN is not set."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(CredentialError, match="GITHUB_TOKEN"):
            get_github_token()
