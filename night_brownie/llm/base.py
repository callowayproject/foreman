"""Abstract LLMBackend base class and factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from night_brownie.config import LLMConfig


class LLMBackend(ABC):
    """Abstract base class for LLM provider backends.

    All concrete backends must implement [`complete`][.].
    """

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        """Send a prompt to the LLM and return the text response.

        Args:
            prompt: The user prompt to send to the model.
            system: Optional system prompt to configure model behaviour.

        Returns:
            The model's text response as a string.
        """


def from_config(config: LLMConfig) -> LLMBackend:
    """Instantiate the correct [`LLMBackend`][LLMBackend] from an [`LLMConfig`][LLMConfig].

    Args:
        config: The LLM section of the Night Brownie runtime config.

    Returns:
        A concrete [`LLMBackend`][LLMBackend] instance.

    Raises:
        ValueError: If `config.provider` is not a supported backend.
    """
    provider = config.provider

    if provider == "anthropic":
        from night_brownie.llm.anthropic import AnthropicBackend

        return AnthropicBackend(config)

    if provider == "ollama":
        from night_brownie.llm.ollama import OllamaBackend

        return OllamaBackend(config)

    raise ValueError(f"Unsupported LLM provider: '{provider}'")
