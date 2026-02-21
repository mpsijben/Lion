"""Auto-assignment of lenses based on task analysis and model affinity.

This module provides:
- TASK_LENS_MAP: keyword-to-lens mappings for common task types
- DEFAULT_LENSES: fallback lenses when no keywords match
- auto_assign_lenses(): select lenses based on task prompt
- assign_lenses_to_providers(): match lenses to models based on affinity
"""

from . import LENSES

# Task-to-lens mapping based on keywords in the prompt
TASK_LENS_MAP: list[dict] = [
    {
        "match": ["payment", "stripe", "checkout", "billing", "invoice"],
        "lenses": ["arch", "sec", "data"],
        "reason": "Payment systems need solid architecture, security, and data integrity",
    },
    {
        "match": ["auth", "login", "session", "jwt", "oauth", "sso", "password"],
        "lenses": ["sec", "arch", "dx"],
        "reason": "Auth is security-critical with user-facing API surface",
    },
    {
        "match": ["api", "endpoint", "route", "rest", "graphql"],
        "lenses": ["arch", "dx", "perf"],
        "reason": "APIs need clean design, good DX, and performance",
    },
    {
        "match": ["database", "migration", "schema", "model", "query"],
        "lenses": ["data", "perf", "maint"],
        "reason": "Database work centers on integrity, speed, and maintainability",
    },
    {
        "match": ["ui", "frontend", "component", "page", "form", "dashboard"],
        "lenses": ["dx", "perf", "maint"],
        "reason": "Frontend needs good UX, fast rendering, and maintainable components",
    },
    {
        "match": ["refactor", "cleanup", "tech debt", "reorganize"],
        "lenses": ["maint", "arch", "quick"],
        "reason": "Refactoring targets maintainability and architecture, pragmatically",
    },
    {
        "match": ["deploy", "docker", "ci", "pipeline", "kubernetes", "infra"],
        "lenses": ["quick", "sec", "cost"],
        "reason": "Infrastructure should ship fast, be secure, and be cost-aware",
    },
    {
        "match": ["scale", "performance", "optimize", "slow", "cache"],
        "lenses": ["perf", "arch", "cost"],
        "reason": "Performance needs profiling focus, architecture, cost awareness",
    },
    {
        "match": ["test", "coverage", "spec", "e2e", "integration test"],
        "lenses": ["test_lens", "maint", "quick"],
        "reason": "Testing needs testability analysis, maintainability, pragmatism",
    },
]

# Default lenses when no keywords match
DEFAULT_LENSES: list[str] = ["arch", "sec", "quick"]


def auto_assign_lenses(prompt: str, n_agents: int) -> list[str]:
    """Select lenses based on the task prompt.

    Analyzes the prompt for keywords and returns the most relevant lenses.
    Falls back to DEFAULT_LENSES if no keywords match.

    Args:
        prompt: The task description to analyze
        n_agents: Number of agents (limits how many lenses to return)

    Returns:
        List of lens shortcodes, up to n_agents in length
    """
    prompt_lower = prompt.lower()

    best_match = None
    best_score = 0

    for mapping in TASK_LENS_MAP:
        score = sum(1 for kw in mapping["match"] if kw in prompt_lower)
        if score > best_score:
            best_score = score
            best_match = mapping

    if best_match and best_score > 0:
        return best_match["lenses"][:n_agents]

    return DEFAULT_LENSES[:n_agents]


def assign_lenses_to_providers(
    providers: list[str], lenses: list[str]
) -> list[tuple[str, str]]:
    """Match lenses to providers based on model affinity.

    Uses the best_models field of each lens to optimally pair
    providers with lenses they're best suited for.

    Args:
        providers: List of provider names (e.g., ["claude", "gemini", "codex"])
        lenses: List of lens shortcodes (e.g., ["sec", "arch", "quick"])

    Returns:
        List of (provider, lens) tuples representing optimal assignments

    Example:
        >>> assign_lenses_to_providers(["claude", "gemini", "codex"], ["sec", "arch", "quick"])
        [("claude", "sec"), ("gemini", "arch"), ("codex", "quick")]
    """
    assignments = []
    available_providers = list(providers)
    available_lenses = list(lenses)

    while available_providers and available_lenses:
        best_score = -1
        best_pair = None

        for p in available_providers:
            for lens_code in available_lenses:
                lens_def = LENSES.get(lens_code)
                if lens_def is None:
                    # Unknown lens, give it a neutral score
                    score = 0.5
                else:
                    # High score if provider is in best_models, lower otherwise
                    score = 1.0 if p in lens_def.best_models else 0.5

                if score > best_score:
                    best_score = score
                    best_pair = (p, lens_code)

        if best_pair:
            assignments.append(best_pair)
            available_providers.remove(best_pair[0])
            available_lenses.remove(best_pair[1])

    return assignments


def get_lens_reason(prompt: str) -> str | None:
    """Get the reason for lens selection based on the task prompt.

    Returns the 'reason' field from the matched task mapping, or None
    if no keywords matched (default lenses were used).

    Args:
        prompt: The task description to analyze

    Returns:
        Reason string explaining lens selection, or None for default
    """
    prompt_lower = prompt.lower()

    best_match = None
    best_score = 0

    for mapping in TASK_LENS_MAP:
        score = sum(1 for kw in mapping["match"] if kw in prompt_lower)
        if score > best_score:
            best_score = score
            best_match = mapping

    if best_match and best_score > 0:
        return best_match["reason"]

    return None


__all__ = [
    "TASK_LENS_MAP",
    "DEFAULT_LENSES",
    "auto_assign_lenses",
    "assign_lenses_to_providers",
    "get_lens_reason",
]
