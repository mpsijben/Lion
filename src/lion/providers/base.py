"""Abstract provider interface and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# Type alias for quota recording callback
QuotaRecorder = Callable[[str, int], bool]


@dataclass
class AgentResult:
    content: str
    model: str
    tokens_used: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None
    session_id: Optional[str] = None
    files_changed: list[str] = field(default_factory=list)


# Global quota recorder callback - set by pipeline or CLI
_quota_recorder: Optional[QuotaRecorder] = None


def set_quota_recorder(recorder: Optional[QuotaRecorder]) -> None:
    """Set the global quota recorder callback.

    This should be called by the pipeline executor or CLI to enable
    automatic quota tracking for all provider calls.

    Args:
        recorder: A callable that takes (model_name, tokens_used) and returns
                  True if recording succeeded. Pass None to disable.
    """
    global _quota_recorder
    _quota_recorder = recorder


def get_quota_recorder() -> Optional[QuotaRecorder]:
    """Get the current quota recorder callback."""
    return _quota_recorder


def record_quota_usage(model: str, tokens: int) -> bool:
    """Record quota usage if a recorder is configured.

    Args:
        model: Model name (e.g., "claude", "gemini")
        tokens: Number of tokens used

    Returns:
        True if recorded successfully or no recorder configured,
        False if recording failed.
    """
    if _quota_recorder is None:
        return True
    return _quota_recorder(model, tokens)


class Provider(ABC):
    """Base class for all LLM providers.

    Providers automatically track quota usage when a QuotaTracker is configured
    via set_quota_recorder(). Call _record_usage() after each LLM call.
    """

    name: str = "base"

    def __init__(self, model: str | None = None, config: dict | None = None):
        self.model_override = model
        self.config = config or {}
        self.timeout = self.config.get("provider_timeout", 480)

    def _record_usage(self, result: AgentResult) -> None:
        """Record token usage from an AgentResult to the quota tracker.

        Call this method after each successful LLM call to track usage.
        Does nothing if no quota recorder is configured.

        Args:
            result: The AgentResult from the LLM call
        """
        if result.success and result.tokens_used > 0:
            record_quota_usage(result.model, result.tokens_used)

    def _get_effective_system_prompt(self, system_prompt: str) -> str:
        """Inject conciseness instruction if configured."""
        if self.config.get("concise", False):
            instruction = "Be extremely concise. Focus on thoughts and code rather than full explanations."
            if system_prompt:
                return f"{instruction}\n\n{system_prompt}"
            return instruction
        return system_prompt

    @abstractmethod
    def ask(self, prompt: str, system_prompt: str = "",
            cwd: str = ".") -> AgentResult:
        pass

    @abstractmethod
    def ask_with_files(self, prompt: str, files: list[str],
                       system_prompt: str = "",
                       cwd: str = ".") -> AgentResult:
        pass

    @abstractmethod
    def implement(self, prompt: str, cwd: str = ".") -> AgentResult:
        pass
