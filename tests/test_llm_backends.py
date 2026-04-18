"""Tests for Anthropic and Ollama LLM backends.

LLM calls are not made live — responses are replayed from recorded fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from foreman.config import LLMConfig
from foreman.llm.anthropic import AnthropicBackend
from foreman.llm.ollama import OllamaBackend

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES_DIR / name).read_text())


class TestAnthropicBackend:
    def test_instantiates_with_config(self):
        cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="test-key")
        backend = AnthropicBackend(cfg)
        assert isinstance(backend, AnthropicBackend)

    def test_complete_returns_string(self):
        fixture = load_fixture("anthropic_triage_response.json")
        cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="test-key")
        backend = AnthropicBackend(cfg)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = fixture["content"]

        with patch("litellm.completion", return_value=mock_response):
            result = backend.complete("triage this issue")

        assert isinstance(result, str)
        assert result == fixture["content"]

    def test_complete_with_system_prompt(self):
        cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="test-key")
        backend = AnthropicBackend(cfg)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response text"

        with patch("litellm.completion", return_value=mock_response) as mock_complete:
            backend.complete("prompt", system="be helpful")
            call_kwargs = mock_complete.call_args
            messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][1]
            # system message should be included
            assert any(m.get("role") == "system" for m in messages)

    def test_complete_passes_model_to_litellm(self):
        cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="test-key")
        backend = AnthropicBackend(cfg)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"

        with patch("litellm.completion", return_value=mock_response) as mock_complete:
            backend.complete("hello")
            call_kwargs = mock_complete.call_args
            model_arg = call_kwargs[1].get("model") or call_kwargs[0][0]
            assert "claude-sonnet-4-6" in model_arg


class TestOllamaBackend:
    def test_instantiates_with_config(self):
        cfg = LLMConfig(provider="ollama", model="llama3")
        backend = OllamaBackend(cfg)
        assert isinstance(backend, OllamaBackend)

    def test_complete_returns_string(self):
        fixture = load_fixture("ollama_triage_response.json")
        cfg = LLMConfig(provider="ollama", model="llama3")
        backend = OllamaBackend(cfg)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = fixture["content"]

        with patch("litellm.completion", return_value=mock_response):
            result = backend.complete("triage this issue")

        assert isinstance(result, str)
        assert result == fixture["content"]

    def test_complete_with_system_prompt(self):
        cfg = LLMConfig(provider="ollama", model="llama3")
        backend = OllamaBackend(cfg)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response"

        with patch("litellm.completion", return_value=mock_response) as mock_complete:
            backend.complete("prompt", system="you are a triage assistant")
            call_kwargs = mock_complete.call_args
            messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][1]
            assert any(m.get("role") == "system" for m in messages)

    def test_complete_passes_ollama_model_format(self):
        cfg = LLMConfig(provider="ollama", model="llama3")
        backend = OllamaBackend(cfg)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"

        with patch("litellm.completion", return_value=mock_response) as mock_complete:
            backend.complete("hello")
            call_kwargs = mock_complete.call_args
            model_arg = call_kwargs[1].get("model") or call_kwargs[0][0]
            # LiteLLM expects "ollama/model-name" format
            assert "llama3" in model_arg
