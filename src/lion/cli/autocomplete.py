"""Context-aware autocomplete for Lion CLI pipelines and command mode.

Provides intelligent completion suggestions for:
- Pipeline functions after -> operator (e.g., "prompt" -> p<TAB> suggests pair(), pride(), pr)
- Model names inside pair() (e.g., pair(c<TAB> suggests claude, codex)
- Lens shortcodes inside pair() eyes: argument (e.g., eyes:s<TAB> suggests sec)
  - Use + to combine multiple lenses: eyes:sec+arch+perf
- Agent count inside pride() (e.g., pride(<TAB> suggests 3, 5, 7)
- Self-heal operator ^ inside review()
- Arrow operator -> after a prompt or function call
"""

from __future__ import annotations

import re
from typing import Iterable

try:
    from prompt_toolkit.completion import Completer, Completion
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    Completer = object  # type: ignore[assignment]
    Completion = object  # type: ignore[assignment]
    PROMPT_TOOLKIT_AVAILABLE = False


def _get_available_functions() -> list[str]:
    """Dynamically get available pipeline functions from the functions module."""
    try:
        from pathlib import Path
        functions_dir = Path(__file__).parent.parent / "functions"
        if functions_dir.exists():
            # Get all .py files except __init__.py and utils.py
            funcs = []
            for f in functions_dir.glob("*.py"):
                name = f.stem
                if name not in ("__init__", "utils"):
                    funcs.append(name)
            return sorted(funcs)
    except Exception:
        pass
    # Fallback to hardcoded list
    return [
        "pair", "pride", "impl", "review", "test", "pr",
        "devil", "future", "create_tests", "lint", "typecheck",
        "audit", "task", "distill", "context_build", "onboard",
        "migrate", "cost", "self_heal"
    ]


def _get_available_providers() -> list[str]:
    """Dynamically get available providers from the providers module."""
    try:
        from ..providers import PROVIDERS
        return list(PROVIDERS.keys())
    except Exception:
        pass
    # Fallback
    return ["claude", "gemini", "codex"]


def _get_available_lenses() -> list[str]:
    """Dynamically get available lens shortcodes from the lenses module."""
    try:
        from ..lenses import list_lenses
        return [lens.shortcode for lens in list_lenses()]
    except Exception:
        pass
    # Fallback
    return ["sec", "arch", "perf", "dx", "test", "quick", "maint", "data", "cost"]


# Functions that take arguments (show with parentheses)
FUNCTIONS_WITH_ARGS = {"pair", "pride", "review", "devil", "future", "task"}

# Pride agent count suggestions
PRIDE_SUGGESTIONS = ["3", "5", "7"]


def _is_fuzzy_match(query: str, candidate: str) -> bool:
    """Check if query characters appear in order within candidate."""
    if not query:
        return True
    it = iter(candidate)
    return all(ch in it for ch in query)


def _rank_matches(prefix: str, choices: Iterable[str], show_all_on_empty: bool = True) -> list[str]:
    """Return prefix matches first, then fuzzy matches.

    Args:
        prefix: The text to match against
        choices: Available options to match
        show_all_on_empty: If True, return all choices when prefix is empty
    """
    prefix = prefix.lower()
    choices_list = list(choices)

    if not prefix and show_all_on_empty:
        return choices_list

    prefix_matches = [c for c in choices_list if c.lower().startswith(prefix)]
    fuzzy_matches = [c for c in choices_list if c not in prefix_matches and _is_fuzzy_match(prefix, c.lower())]
    return prefix_matches + fuzzy_matches


def _extract_last_token(text_before_cursor: str) -> str:
    """Extract the token currently being typed."""
    m = re.search(r"([a-zA-Z0-9_\-\^]*)$", text_before_cursor)
    return m.group(1) if m else ""


def _after_arrow(text: str) -> bool:
    """Check if cursor is after -> operator, ready for function name."""
    return bool(re.search(r"->\s*[a-zA-Z0-9_]*$", text))


def _inside_pair_model(text: str) -> bool:
    """Check if cursor is inside pair() expecting a model name."""
    m = re.search(r"pair\(([^)]*)$", text)
    if not m:
        return False
    inside = m.group(1)
    return "," not in inside


def _inside_pair_eyes(text: str) -> bool:
    """Check if cursor is inside pair() eyes: argument expecting lens names.

    Lens syntax: eyes:lens1+lens2+lens3
    Use + to combine multiple lenses for the reviewing agents.
    """
    m = re.search(r"pair\(([^)]*)$", text)
    if not m:
        return False
    inside = m.group(1)
    return "eyes:" in inside


def _inside_pride(text: str) -> bool:
    """Check if cursor is inside pride() expecting agent count."""
    return bool(re.search(r"pride\(([^)]*)$", text))


def _inside_review(text: str) -> bool:
    """Check if cursor is inside review() expecting ^ self-heal operator."""
    return bool(re.search(r"review\(([^)]*)$", text))


def _used_lenses(text: str) -> set[str]:
    """Extract lenses already used in eyes: argument.

    Parses syntax like 'eyes:sec+arch' and returns {'sec', 'arch'}.
    """
    m = re.search(r"eyes:\s*([^),]*)$", text)
    if not m:
        return set()
    current = m.group(1)
    values = [v.strip().lower() for v in current.split("+") if v.strip()]
    return set(values)


def _has_prompt(text: str) -> bool:
    """Check if input has a completed quoted prompt."""
    return bool(re.search(r'^"[^"]+"\s*', text) or re.search(r"^'[^']+'\s*", text))


def _ends_with_closed_paren(text: str) -> bool:
    """Check if text ends with a closed function call."""
    return bool(re.search(r"\)\s*$", text.rstrip()))


def _ends_with_function_no_parens(text: str) -> bool:
    """Check if text ends with a function name that doesn't have parens yet."""
    functions = _get_available_functions()
    for func in functions:
        if re.search(rf"\b{func}\s*$", text):
            return True
    return False


def _format_function(name: str) -> str:
    """Format a function name, adding () for functions that take arguments."""
    if name in FUNCTIONS_WITH_ARGS:
        return f"{name}()"
    return name


def get_pipeline_completions(text_before_cursor: str) -> list[tuple[str, int]]:
    """Get context-aware pipeline completion suggestions for current cursor context.

    Returns:
        List of (completion_text, cursor_offset) tuples.
        cursor_offset is negative to position cursor inside parentheses.
    """
    token = _extract_last_token(text_before_cursor)
    text = text_before_cursor.rstrip()

    # After -> operator, suggest functions
    if _after_arrow(text_before_cursor):
        functions = _get_available_functions()
        matches = _rank_matches(token, functions)
        result = []
        for name in matches:
            if name in FUNCTIONS_WITH_ARGS:
                # Position cursor inside parentheses: pair(|)
                result.append((f"{name}()", -1))
            else:
                result.append((name, 0))
        return result

    # Inside pair() first argument - suggest models
    if _inside_pair_model(text_before_cursor):
        providers = _get_available_providers()
        return [(p, 0) for p in _rank_matches(token, providers)]

    # Inside pair() eyes: argument - suggest lenses
    if _inside_pair_eyes(text_before_cursor):
        all_lenses = _get_available_lenses()
        used = _used_lenses(text_before_cursor)
        remaining = [lens for lens in all_lenses if lens not in used]
        return [(lens, 0) for lens in _rank_matches(token, remaining)]

    # Inside pride() - suggest agent count
    if _inside_pride(text_before_cursor):
        matches = [x for x in PRIDE_SUGGESTIONS if not token or x.startswith(token)]
        return [(m, 0) for m in matches]

    # Inside review() - suggest self-heal operator
    if _inside_review(text_before_cursor):
        if not token or "^".startswith(token):
            return [("^", 0)]
        return []

    # After a prompt or after a function call, suggest -> arrow
    if not token and (_has_prompt(text) or _ends_with_closed_paren(text)):
        if not text.endswith("->"):
            return [("-> ", 0)]

    # Show all functions if typing something that looks like start of pipeline
    if token and not text_before_cursor.strip().startswith(":"):
        functions = _get_available_functions()
        matches = _rank_matches(token, functions, show_all_on_empty=False)
        if matches:
            result = []
            for name in matches:
                if name in FUNCTIONS_WITH_ARGS:
                    result.append((f"{name}()", -1))
                else:
                    result.append((name, 0))
            return result

    return []


def get_pipeline_completions_simple(text_before_cursor: str) -> list[str]:
    """Simple version returning just completion strings (for readline)."""
    return [text for text, _ in get_pipeline_completions(text_before_cursor)]


def get_repl_completions(text_before_cursor: str, command_completions: list[str]) -> list[str]:
    """Return completion candidates for either :commands or pipeline input."""
    stripped = text_before_cursor.lstrip()
    if stripped.startswith(":"):
        return command_completions
    return get_pipeline_completions_simple(text_before_cursor)


class LionPromptToolkitCompleter(Completer):
    """Prompt-toolkit completer implementing Lion context-aware suggestions.

    Provides intelligent completions for:
    - Pipeline functions: pair(), pride(), impl, review(), test, pr, etc.
    - Models inside pair(): claude, gemini, codex
    - Lenses inside pair() eyes:: sec, arch, perf, dx, etc.
    - Agent counts inside pride(): 3, 5, 7
    - Self-heal operator in review(): ^
    - Arrow operator after prompts: ->
    """

    def __init__(self, command_completions_func=None):
        """Initialize completer.

        Args:
            command_completions_func: Optional function that returns :command completions
        """
        self.command_completions_func = command_completions_func

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        token = _extract_last_token(text)

        # Handle :commands
        if text.lstrip().startswith(":"):
            if self.command_completions_func:
                for cmd in self.command_completions_func(text):
                    yield Completion(cmd, start_position=-len(text.lstrip()))
            return

        # Handle pipeline completions
        for suggestion, cursor_offset in get_pipeline_completions(text):
            start_position = -len(token) if token else 0
            # For -> we don't want to replace any token
            if suggestion.startswith("->"):
                start_position = 0
            yield Completion(
                suggestion,
                start_position=start_position,
                # Move cursor inside parens if needed
                selected_text=suggestion[:len(suggestion) + cursor_offset] if cursor_offset else None
            )
