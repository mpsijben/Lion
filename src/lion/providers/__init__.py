"""Provider registry."""

from .claude import ClaudeProvider

PROVIDERS = {
    "claude": ClaudeProvider,
}


def get_provider(name: str, config: dict = None):
    """Get a provider instance by name."""
    if name in PROVIDERS:
        return PROVIDERS[name]()
    raise ValueError(f"Unknown provider: {name}. Available: {list(PROVIDERS.keys())}")
