"""Provider registry."""

from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .codex import CodexProvider

PROVIDERS = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "codex": CodexProvider,
}


def get_provider(name: str, config: dict = None):
    """Get a provider instance by name."""
    if name in PROVIDERS:
        return PROVIDERS[name]()
    raise ValueError(f"Unknown provider: {name}. Available: {list(PROVIDERS.keys())}")
