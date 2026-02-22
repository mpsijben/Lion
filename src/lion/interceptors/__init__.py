"""Stream interceptors for CLI process-level LLM control.

Interceptors wrap LLM CLIs (Claude, Gemini, Codex) as OS processes
that can be started, streamed, terminated, and resumed. This enables
closed-loop control over LLM generation via stream interruption.
"""

import shutil

from .base import Chunk, StreamInterceptor, StreamStats
from .claude import ClaudeInterceptor
from .gemini import GeminiInterceptor
from .codex import CodexInterceptor

INTERCEPTORS = {
    "claude": ClaudeInterceptor,
    "gemini": GeminiInterceptor,
    "codex": CodexInterceptor,
}


def get_interceptor(name: str, cwd: str = ".") -> StreamInterceptor:
    """Get an interceptor by provider name.

    Accepts "claude", "gemini", "codex" or dotted forms like "claude.opus"
    (the part after the dot is ignored here -- model selection is handled
    by the interceptor's build_command).
    """
    provider_name = name.split(".", 1)[0].lower()
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
    return cls(cwd=cwd)


__all__ = [
    "Chunk",
    "StreamInterceptor",
    "StreamStats",
    "ClaudeInterceptor",
    "GeminiInterceptor",
    "CodexInterceptor",
    "INTERCEPTORS",
    "get_interceptor",
]
