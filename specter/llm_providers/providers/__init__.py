"""LLM Provider implementations.

This package contains concrete implementations of the LLMProvider protocol
for various LLM backends.

Available Providers:
    - OpenRouterProvider: OpenRouter API (unified access to multiple providers)
    - AnthropicProvider: Direct Anthropic API
    - OpenAIProvider: Direct OpenAI API
"""

try:
    from .anthropic import AnthropicProvider
except ImportError:
    AnthropicProvider = None  # type: ignore[assignment,misc]

try:
    from .openai import OpenAIProvider
except ImportError:
    OpenAIProvider = None  # type: ignore[assignment,misc]

from .openrouter import OpenRouterProvider

__all__ = [
    "AnthropicProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
]
