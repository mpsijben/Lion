"""Abstract provider interface and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentResult:
    content: str
    model: str
    tokens_used: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None


class Provider(ABC):
    """Base class for all LLM providers."""

    name: str = "base"

    def __init__(self, model: str | None = None):
        self.model_override = model

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
