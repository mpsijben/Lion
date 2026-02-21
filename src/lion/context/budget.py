"""Context Budget Manager for automatic context compression.

Manages token budgets across pipeline steps and triggers auto-distill
when context exceeds configured thresholds.
"""

import time
from typing import TYPE_CHECKING

from .parser import estimate_tokens

if TYPE_CHECKING:
    from ..memory import SharedMemory, MemoryEntry
    from ..parser import PipelineStep


class ContextBudgetManager:
    """Automatically manages context size across pipeline steps."""

    def __init__(self, config: dict):
        """Initialize the budget manager.

        Args:
            config: Lion configuration dict with [context] section
        """
        context_config = config.get("context", {})
        self.max_per_step = context_config.get("max_context_tokens_per_step", 4000)
        self.max_total = context_config.get("max_total_context_tokens", 15000)
        self.auto_distill = context_config.get("auto_distill", True)
        self.distill_provider = context_config.get("distill_provider", "gemini")
        self.total_used = 0

    def should_distill(self, current_context_tokens: int) -> bool:
        """Check if we need to compress before the next step."""
        return self.auto_distill and current_context_tokens > self.max_per_step

    def prepare_context_for_step(self, memory: "SharedMemory", step: "PipelineStep",
                                 config: dict, cwd: str) -> str:
        """Get context for next step, auto-compressing if needed.

        Args:
            memory: SharedMemory instance
            step: The pipeline step about to be executed
            config: Lion configuration
            cwd: Working directory

        Returns:
            Context text appropriate for this step
        """
        # Check if distilled context exists
        distilled = memory.read_phase("distill")
        if distilled:
            # Use most recent distillation
            return distilled[-1].content

        # Calculate raw context size
        relevant = self._get_relevant_entries(memory, step)
        context_text = memory.format_for_prompt(relevant)
        context_tokens = estimate_tokens(context_text)

        self.total_used += context_tokens

        if self.should_distill(context_tokens):
            # Auto-compress
            compressed = self._auto_distill(
                context_text, context_tokens, memory, config, cwd
            )
            return compressed

        return context_text

    def _get_relevant_entries(self, memory: "SharedMemory",
                              step: "PipelineStep") -> list:
        """Get only the memory entries relevant to this step.

        Different steps need different context:
        - devil/future: decisions + uncertainties + compressed context
        - review: code + decisions
        - test: code only
        """
        all_entries = memory.read_all()

        # For devil/future: they need decisions + uncertainties
        if step.function in ("devil", "future"):
            return [e for e in all_entries
                    if e.type in ("decision", "proposal", "compressed_context",
                                  "shared_context", "historical_context")]

        # For review: needs code + decisions
        if step.function == "review":
            return [e for e in all_entries
                    if e.type in ("code", "decision", "compressed_context",
                                  "shared_context")]

        # For test: just code
        if step.function == "test":
            return [e for e in all_entries if e.type == "code"]

        # For audit: code + dependencies
        if step.function == "audit":
            return [e for e in all_entries
                    if e.type in ("code", "decision")]

        # Default: everything
        return all_entries

    def _auto_distill(self, context_text: str, context_tokens: int,
                      memory: "SharedMemory", config: dict, cwd: str) -> str:
        """Automatically compress context when budget is exceeded.

        Args:
            context_text: Full context text to compress
            context_tokens: Token count of full context
            memory: SharedMemory instance
            config: Lion configuration
            cwd: Working directory

        Returns:
            Compressed context text
        """
        from ..providers import get_provider
        from .prompts import DISTILL_PROMPT

        # Target: compress to 25% of original, minimum 500, maximum 3000
        target_tokens = max(500, min(3000, context_tokens // 4))

        # Use configured distill provider
        provider = get_provider(self.distill_provider, config)

        distill_prompt = DISTILL_PROMPT.format(
            deliberation=context_text,
            token_count=context_tokens,
            target_tokens=target_tokens
        )

        result = provider.ask(distill_prompt, "", cwd)

        if result.success and result.content:
            # Store compressed context in memory
            from ..memory import MemoryEntry
            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="distill",
                agent="auto_distiller",
                type="compressed_context",
                content=result.content,
                metadata={
                    "auto": True,
                    "trigger": "budget_exceeded",
                    "original_tokens": context_tokens,
                    "compressed_tokens": estimate_tokens(result.content),
                    "model": result.model,
                }
            ))
            return result.content

        # Fallback: truncate if distillation fails
        return context_text[:self.max_per_step * 4]  # ~4 chars per token

    def get_budget_status(self) -> dict:
        """Get current budget usage status."""
        return {
            "total_used": self.total_used,
            "max_per_step": self.max_per_step,
            "max_total": self.max_total,
            "remaining": max(0, self.max_total - self.total_used),
            "over_budget": self.total_used > self.max_total,
        }


def select_context_mode(pipeline_steps: list, config: dict) -> str:
    """Select context mode based on pipeline complexity.

    Auto-scales from minimal to rich based on:
    - Presence of "deep thinking" functions (devil, future, audit)
    - Number of pride agents
    - User override in config

    Args:
        pipeline_steps: List of PipelineStep objects
        config: Lion configuration dict

    Returns:
        "minimal", "standard", or "rich"
    """
    # User override always wins
    context_config = config.get("context", {})
    if context_config.get("default_mode") and context_config["default_mode"] != "auto":
        return context_config["default_mode"]

    # Check CLI override (passed through config)
    if config.get("context_mode"):
        mode = config["context_mode"]
        if mode != "auto":
            return mode

    # Count "deep thinking" functions
    deep_functions = {"devil", "future", "audit", "explain"}
    has_deep = any(s.function in deep_functions for s in pipeline_steps)

    # Find max pride agent count
    pride_steps = [s for s in pipeline_steps if s.function == "pride"]
    max_agents = 0
    for s in pride_steps:
        if s.args and isinstance(s.args[0], int):
            max_agents = max(max_agents, s.args[0])
        else:
            max_agents = max(max_agents, 3)  # Default pride size

    # Selection logic
    if has_deep or max_agents >= 4:
        return "rich"
    elif pride_steps:
        return "standard"
    else:
        return "minimal"
