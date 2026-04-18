"""Tests for foreman/llm/base.py — LLMBackend ABC and factory."""

from __future__ import annotations

import pytest

from foreman.config import LLMConfig
from foreman.llm.base import LLMBackend, from_config


class ConcreteBackend(LLMBackend):
    """Minimal concrete implementation for ABC testing."""

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Return a fixed response."""
        return "response"


class TestLLMBackendABC:
    def test_cannot_instantiate_abc_directly(self):
        with pytest.raises(TypeError):
            LLMBackend()  # type: ignore[abstract]

    def test_concrete_subclass_is_instantiable(self):
        backend = ConcreteBackend()
        assert isinstance(backend, LLMBackend)

    def test_complete_returns_string(self):
        backend = ConcreteBackend()
        result = backend.complete("hello")
        assert isinstance(result, str)

    def test_complete_accepts_optional_system(self):
        backend = ConcreteBackend()
        result = backend.complete("hello", system="you are helpful")
        assert isinstance(result, str)


class TestFromConfigFactory:
    def test_returns_anthropic_backend_for_anthropic_provider(self):
        from foreman.llm.anthropic import AnthropicBackend

        cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="test-key")
        backend = from_config(cfg)
        assert isinstance(backend, AnthropicBackend)

    def test_returns_ollama_backend_for_ollama_provider(self):
        from foreman.llm.ollama import OllamaBackend

        cfg = LLMConfig(provider="ollama", model="llama3")
        backend = from_config(cfg)
        assert isinstance(backend, OllamaBackend)

    def test_unknown_provider_raises_value_error(self):
        cfg = LLMConfig(provider="unknown-provider", model="some-model")
        with pytest.raises(ValueError, match="unknown-provider"):
            from_config(cfg)

    def test_factory_returns_llm_backend_instance(self):
        cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="test-key")
        backend = from_config(cfg)
        assert isinstance(backend, LLMBackend)
