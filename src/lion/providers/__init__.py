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
    """Check if a string is a valid provider name (with optional model)."""
    if not isinstance(name, str):
        return False
    provider_name = name.split(".", 1)[0]
    return provider_name in PROVIDERS


def get_provider(name: str, config: dict = None):
    """Get a provider instance by name.

    Supports model selection with dot syntax:
        claude          -> ClaudeProvider()
        claude.haiku    -> ClaudeProvider(model="haiku")
        claude.opus     -> ClaudeProvider(model="opus")
        claude.sonnet   -> ClaudeProvider(model="sonnet")
        gemini.flash    -> GeminiProvider(model="gemini-2.0-flash")
        gemini.pro      -> GeminiProvider(model="gemini-2.5-pro")
    """
    # Split provider.model syntax
    parts = name.split(".", 1)
    provider_name = parts[0]
    model = parts[1] if len(parts) > 1 else None

    if provider_name not in PROVIDERS:
        raise ValueError(
            f"Unknown provider: {provider_name}. "
            f"Available: {list(PROVIDERS.keys())}"
        )

    return PROVIDERS[provider_name](model=model)
