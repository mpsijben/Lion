"""Shared self-healing loop utility for validation steps.

Extracts the common pattern used in review, devil, future, lint, and typecheck
functions to reduce code duplication and centralize cost tracking.
"""

import time
from typing import Callable, Optional, Any
from dataclasses import dataclass

from ..display import Display
from ..providers.base import Provider


# Provider-specific cost rates per 1M tokens
# Rates as of 2024: input_cost, output_cost per 1M tokens
PROVIDER_COST_RATES = {
    # Claude models
    "claude": {"input": 15.0, "output": 75.0},  # Claude Opus default
    "claude.opus": {"input": 15.0, "output": 75.0},
    "claude.sonnet": {"input": 3.0, "output": 15.0},
    "claude.haiku": {"input": 0.25, "output": 1.25},
    # Gemini models
    "gemini": {"input": 0.075, "output": 0.30},  # Gemini Flash default
    "gemini.flash": {"input": 0.075, "output": 0.30},
    "gemini.pro": {"input": 1.25, "output": 5.0},
    # Codex/OpenAI models
    "codex": {"input": 3.0, "output": 15.0},  # GPT-4 default
    "openai": {"input": 3.0, "output": 15.0},
    # Fallback for unknown providers
    "default": {"input": 3.0, "output": 15.0},
}

# Backoff delay between healing rounds to prevent rapid token burn
HEAL_BACKOFF_SECONDS = 1.0


def estimate_cost(provider_name: str, tokens: int, is_output: bool = True) -> float:
    """Estimate cost for a given number of tokens.

    Args:
        provider_name: Name of the provider (e.g., "claude", "gemini.flash")
        tokens: Number of tokens
        is_output: If True, use output rate (more expensive). If False, use input rate.

    Returns:
        Estimated cost in dollars
    """
    # Normalize provider name
    provider_key = provider_name.lower()

    # Try exact match, then base provider, then default
    if provider_key in PROVIDER_COST_RATES:
        rates = PROVIDER_COST_RATES[provider_key]
    elif "." in provider_key:
        base_provider = provider_key.split(".")[0]
        rates = PROVIDER_COST_RATES.get(base_provider, PROVIDER_COST_RATES["default"])
    else:
        rates = PROVIDER_COST_RATES["default"]

    rate_key = "output" if is_output else "input"
    cost_per_million = rates[rate_key]

    return (tokens / 1_000_000) * cost_per_million


@dataclass
class SelfHealResult:
    """Result from a self-healing loop."""
    passed: bool
    issues: list[dict]
    content: str
    rounds_used: int
    total_tokens: int
    files_changed: list[str]
    cost_limit_reached: bool = False


def self_heal_loop(
    check_fn: Callable[[], tuple[bool, list, str, int]],
    fix_prompt_builder: Callable[[str], str],
    provider: Provider,
    cwd: str,
    max_rounds: int = 2,
    max_cost: Optional[float] = None,
    cost_manager: Any = None,
    provider_name: str = "claude",
    display_name: str = "self-heal",
    initial_files_changed: Optional[list[str]] = None,
) -> SelfHealResult:
    """Run a self-healing loop: check -> fix -> re-check until passing or max rounds.

    Args:
        check_fn: Function that returns (passed: bool, issues: list, content: str, tokens: int).
                  Called each round to validate the current state.
        fix_prompt_builder: Function that takes the check content and returns a fix prompt.
        provider: Provider instance with implement() method for fixing.
        cwd: Working directory for provider.implement().
        max_rounds: Maximum number of fix attempts (default 2).
        max_cost: Optional maximum cost limit for this healing loop.
        cost_manager: Optional cost manager for tracking.
        provider_name: Name of provider for cost tracking.
        display_name: Name to show in Display notifications.
        initial_files_changed: Initial files changed list to extend.

    Returns:
        SelfHealResult with final state after healing loop.
    """
    all_files_changed = list(initial_files_changed or [])
    total_tokens = 0
    cost_limit_reached = False

    # Initial check
    passed, issues, content, tokens_used = check_fn()
    total_tokens += tokens_used

    if cost_manager and tokens_used:
        cost_manager.add_cost(provider_name, tokens_used)

    # Track cumulative cost estimate using provider-specific rates
    cumulative_cost = estimate_cost(provider_name, tokens_used, is_output=True)

    # Initialize round_num before loop in case passed=True on first check
    round_num = 0
    for round_num in range(max_rounds):
        # Check if we should stop
        if passed or not issues:
            break

        # Check cost limit
        if max_cost and cumulative_cost >= max_cost:
            Display.notify(f"Cost limit reached ({cumulative_cost:.4f} >= {max_cost}), stopping {display_name}")
            cost_limit_reached = True
            break

        # Add backoff delay between healing rounds to prevent rapid token burn
        if round_num > 0:
            time.sleep(HEAL_BACKOFF_SECONDS)

        # Attempt fix
        Display.phase(display_name, f"Self-healing round {round_num + 1}/{max_rounds}...")

        fix_prompt = fix_prompt_builder(content)
        fix_result = provider.implement(fix_prompt, cwd)

        total_tokens += fix_result.tokens_used
        cumulative_cost += estimate_cost(provider_name, fix_result.tokens_used, is_output=True)

        if cost_manager and fix_result.tokens_used:
            cost_manager.add_cost(provider_name, fix_result.tokens_used)

        if not fix_result.success:
            Display.step_error(display_name, f"Fix failed: {fix_result.error or 'Unknown error'}")
            break

        # Track files changed by fix
        if hasattr(fix_result, 'files_changed') and fix_result.files_changed:
            all_files_changed.extend(fix_result.files_changed)

        # Re-check after fix
        Display.notify(f"Re-checking after {display_name} fix...")
        passed, issues, content, tokens_used = check_fn()
        total_tokens += tokens_used
        cumulative_cost += estimate_cost(provider_name, tokens_used, is_output=True)

        if cost_manager and tokens_used:
            cost_manager.add_cost(provider_name, tokens_used)

    # Check if we exhausted all rounds without passing
    # This check is outside the loop to handle the case where the loop ran to completion
    # round_num is 0-indexed, so if we ran all max_rounds iterations, round_num == max_rounds - 1
    if not passed and round_num >= max_rounds - 1:
        Display.notify(f"Max {display_name} rounds reached. Continuing with remaining issues.")

    return SelfHealResult(
        passed=passed,
        issues=issues,
        content=content,
        rounds_used=round_num + 1,  # Always add 1 since initial check counts as a round
        total_tokens=total_tokens,
        files_changed=list(set(all_files_changed)),
        cost_limit_reached=cost_limit_reached,
    )


def extract_critical_issues(issues: list[dict]) -> list[dict]:
    """Extract critical issues from an issues list."""
    return [i for i in issues if i.get("severity") == "critical"]


def extract_warning_issues(issues: list[dict]) -> list[dict]:
    """Extract warning issues from an issues list."""
    return [i for i in issues if i.get("severity") == "warning"]


def extract_suggestion_issues(issues: list[dict]) -> list[dict]:
    """Extract suggestion issues from an issues list."""
    return [i for i in issues if i.get("severity") == "suggestion"]
