"""Provider registry."""

from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .codex import CodexProvider

PROVIDERS = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "codex": CodexProvider,
}


def is_provider_name(name: str) -> bool:
    """Check if a string is a valid provider name (with optional model/lens)."""
    if not isinstance(name, str):
        return False
    # Strip lens syntax (provider::lens) first
    provider_part = name.split("::", 1)[0]
    # Strip model syntax (provider.model)
    provider_name = provider_part.split(".", 1)[0]
    return provider_name in PROVIDERS


def get_provider(name: str, config: dict = None):
    """Get a provider instance by name.

    Supports model selection with dot syntax and lens stripping:
        claude          -> ClaudeProvider()
        claude.haiku    -> ClaudeProvider(model="haiku")
        claude::arch    -> ClaudeProvider() (lens is handled elsewhere)
        claude.haiku::sec -> ClaudeProvider(model="haiku")
    """
    # Strip lens syntax first (provider::lens or provider.model::lens)
    provider_part = name.split("::", 1)[0]

    # Split provider.model syntax
    parts = provider_part.split(".", 1)
    provider_name = parts[0]
    model = parts[1] if len(parts) > 1 else None

    if provider_name not in PROVIDERS:
        raise ValueError(
            f"Unknown provider: {provider_name}. "
            f"Available: {list(PROVIDERS.keys())}"
        )

    return PROVIDERS[provider_name](model=model)
