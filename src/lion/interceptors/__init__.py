"""Stream interceptors for CLI process-level LLM control.

Interceptors wrap LLM CLIs (Claude, Gemini, Codex) as OS processes
that can be started, streamed, terminated, and resumed. This enables
closed-loop control over LLM generation via stream interruption.
"""

import shutil

from .base import (
    Chunk,
    InterceptorCapabilities,
    StreamInterceptor,
    StreamStats,
)
from .claude import ClaudeInterceptor
from .claude_live import ClaudeLiveInterceptor
from .gemini import GeminiInterceptor
from .gemini_acp import GeminiACPInterceptor
from .codex import CodexInterceptor
from .codex_app_server import CodexAppServerInterceptor

INTERCEPTORS = {
    "claude": ClaudeInterceptor,
    "gemini": GeminiInterceptor,
    "codex": CodexInterceptor,
}


def get_interceptor(name: str, cwd: str = ".") -> StreamInterceptor:
    """Get an interceptor by provider name.

    Accepts "claude", "gemini", "codex" or dotted forms like "claude.opus",
    "gemini.flash". The part after the dot is passed as model_hint to the
    interceptor for CLI-level model selection.
    """
    parts = name.split(".", 1)
    provider_name = parts[0].lower()
    model_hint = parts[1] if len(parts) > 1 else None

    cls = INTERCEPTORS.get(provider_name)
    if cls is None:
        available = ", ".join(INTERCEPTORS.keys())
        raise ValueError(
            f"Unknown interceptor: {provider_name}. Available: {available}"
        )
    cli_name = provider_name
    if not shutil.which(cli_name):
        raise RuntimeError(
            f"CLI '{cli_name}' not found in PATH. "
            f"Install it or check your PATH to use {provider_name} as interceptor."
        )
    return cls(cwd=cwd, model_hint=model_hint)


__all__ = [
    "Chunk",
    "InterceptorCapabilities",
    "StreamInterceptor",
    "StreamStats",
    "ClaudeInterceptor",
    "ClaudeLiveInterceptor",
    "GeminiInterceptor",
    "GeminiACPInterceptor",
    "CodexInterceptor",
    "CodexAppServerInterceptor",
    "INTERCEPTORS",
    "get_interceptor",
]
