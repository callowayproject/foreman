"""Ollama LLM backend via LiteLLM."""

from __future__ import annotations

from typing import TYPE_CHECKING

import litellm

from foreman.llm.base import LLMBackend

if TYPE_CHECKING:
    from foreman.config import LLMConfig


class OllamaBackend(LLMBackend):
    """LLM backend that calls Ollama models through LiteLLM.

    Args:
        config: The LLM configuration section from the Foreman runtime config.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._model = f"ollama/{config.model}"

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Send a prompt to an Ollama model and return the text response.

        Args:
            prompt: The user prompt to send to the model.
            system: Optional system prompt.

        Returns:
            The model's text response.
        """
        messages = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = litellm.completion(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content
