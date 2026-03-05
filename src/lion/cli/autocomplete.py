"""Context-aware autocomplete for Lion CLI pipelines and command mode.

Provides intelligent completion suggestions for:
- Pipeline functions after -> operator (e.g., "prompt" -> p<TAB> suggests pair(), pride(), pr)
- Model names inside pair() (e.g., pair(c<TAB> suggests claude, codex)
- Model variants with dot syntax (e.g., claude.h<TAB> suggests claude.haiku)
- Lens shortcodes inside pair() eyes: argument (e.g., eyes:s<TAB> suggests sec)
  - Use + to combine multiple lenses: eyes:sec+arch+perf
- Lens syntax with :: (e.g., claude::<TAB> suggests ::arch, ::sec, etc.)
- Agent count inside pride() (e.g., pride(<TAB> suggests 3, 5, 7)
- Self-heal operator ^ inside review()
- Arrow operator -> after a prompt or function call (only when syntax is valid)
- Keyword arguments like model:, eyes:, lenses: inside functions
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


def _get_model_variants(provider: str) -> list[str]:
    """Get model variants for a provider.

    Returns common model names that can be used with dot syntax:
        claude.haiku, claude.sonnet, claude.opus
        gemini.flash, gemini.pro
        codex.mini
    """
    variants = {
        "claude": ["haiku", "sonnet", "opus"],
        "gemini": ["flash", "pro", "2.5-flash", "2.5-pro"],
        "codex": ["mini", "o3-mini", "o1"],
    }
    return variants.get(provider, [])


# Functions that take arguments (show with parentheses)
FUNCTIONS_WITH_ARGS = {"pair", "pride", "fuse", "review", "devil", "future", "task"}

# Pride agent count suggestions
PRIDE_SUGGESTIONS = ["3", "5", "7"]

# Function-specific keyword arguments
FUNCTION_KWARGS = {
    "pair": ["model", "eyes", "lead"],
    "pride": ["lenses", "model"],
    "review": ["model"],
    "devil": ["model"],
    "future": ["horizon"],
    "task": ["depth"],
    "impl": ["model"],
    "test": ["fix"],
    "lint": ["fix"],
    "typecheck": ["fix"],
}


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
    """Extract the token currently being typed.

    Includes dots and colons for model/lens syntax like:
        claude.ha -> "claude.ha"
        claude:: -> "claude::"
        claude::ar -> "claude::ar"
    """
    # Match tokens with dots, colons, and alphanumeric chars
    m = re.search(r"([a-zA-Z0-9_\-\.\:]+)$", text_before_cursor)
    return m.group(1) if m else ""


def _extract_simple_token(text_before_cursor: str) -> str:
    """Extract just the alphanumeric token (no special chars)."""
    m = re.search(r"([a-zA-Z0-9_]*)$", text_before_cursor)
    return m.group(1) if m else ""


def _after_arrow(text: str) -> bool:
    """Check if cursor is after -> operator, ready for function name."""
    return bool(re.search(r"->\s*[a-zA-Z0-9_]*$", text))


def _is_valid_partial_pipeline(text: str) -> bool:
    """Check if the text so far represents a valid partial pipeline.

    Used to determine if we should suggest the -> arrow operator.
    Returns True if:
    - Text is just a quoted prompt
    - Text ends with a complete function call like pride(3)
    - Text is partially valid (no syntax errors)
    """
    text = text.strip()
    if not text:
        return False

    # Check for balanced quotes
    single_quotes = text.count("'") - text.count("\\'")
    double_quotes = text.count('"') - text.count('\\"')
    if single_quotes % 2 != 0 or double_quotes % 2 != 0:
        return False

    # Check for balanced parentheses
    paren_depth = 0
    in_quote = False
    quote_char = None
    for char in text:
        if char in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = char
        elif char == quote_char and in_quote:
            in_quote = False
            quote_char = None
        elif not in_quote:
            if char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
                if paren_depth < 0:
                    return False

    if paren_depth != 0:
        return False

    # Check if we have a valid prompt
    if not _has_prompt(text):
        return False

    return True


def _get_current_function(text: str) -> str | None:
    """Get the function name we're currently inside of.

    Examples:
        "prompt" -> pair( -> "pair"
        "prompt" -> pride(3, -> "pride"
        "prompt" -> review() -> None (closed)
    """
    # Find the last unclosed function call
    paren_depth = 0
    in_quote = False
    quote_char = None
    last_func_start = -1

    for i, char in enumerate(text):
        if char in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = char
        elif char == quote_char and in_quote:
            in_quote = False
            quote_char = None
        elif not in_quote:
            if char == "(":
                # Check if this is a function call
                before = text[:i].rstrip()
                match = re.search(r"([a-zA-Z_]\w*)$", before)
                if match:
                    if paren_depth == 0:
                        last_func_start = i
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
                if paren_depth == 0:
                    last_func_start = -1

    if last_func_start > 0:
        before = text[:last_func_start].rstrip()
        match = re.search(r"([a-zA-Z_]\w*)$", before)
        if match:
            return match.group(1).lower()
    return None


def _get_arg_context(text: str) -> tuple[str | None, str, int]:
    """Get the context of the current argument position.

    Returns:
        (function_name, current_token, arg_position)

    Examples:
        "prompt" -> pair(cla -> ("pair", "cla", 0)
        "prompt" -> pair(claude, e -> ("pair", "e", 1)
        "prompt" -> pride(3, lens -> ("pride", "lens", 1)
    """
    func = _get_current_function(text)
    if not func:
        return (None, "", 0)

    # Find the content inside the function parens
    match = re.search(rf"{func}\(([^)]*)$", text, re.IGNORECASE)
    if not match:
        return (func, "", 0)

    inside = match.group(1)

    # Count argument position (commas outside quotes)
    arg_pos = 0
    in_quote = False
    quote_char = None
    for char in inside:
        if char in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = char
        elif char == quote_char and in_quote:
            in_quote = False
            quote_char = None
        elif char == "," and not in_quote:
            arg_pos += 1

    # Get current token being typed
    # Split by comma and get last part
    parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', inside)
    current = parts[-1].strip() if parts else ""

    return (func, current, arg_pos)


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
    """Check if input has a prompt (quoted or unquoted).

    In Lion, the prompt is everything before the first ->. Prompts can be:
    - Quoted: "fix the bug" -> ...
    - Unquoted: fix the bug -> ...
    Any non-empty text counts as a prompt.
    """
    stripped = text.strip()
    if not stripped:
        return False
    # Quoted prompt
    if re.search(r'^"[^"]+"\s*', text) or re.search(r"^'[^']+'\s*", text):
        return True
    # Unquoted prompt - any non-empty text that doesn't start with a function call
    # (at minimum some text exists before any ->)
    return bool(stripped)


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

    Supports:
        - Functions after ->: pair(), pride(), impl, review(), etc.
        - Models inside functions: claude, gemini, codex
        - Model variants: claude.haiku, claude.sonnet, gemini.flash
        - Lens syntax: claude::arch, claude::sec
        - Keyword arguments: model:, eyes:, lenses:
        - Lens values: arch, sec, perf, etc.
        - Pride agent counts: 3, 5, 7
        - Self-heal operator: ^
        - Arrow operator: -> (only when syntax is valid)
    """
    token = _extract_last_token(text_before_cursor)
    simple_token = _extract_simple_token(text_before_cursor)
    text = text_before_cursor.rstrip()

    # Get current function context
    func, current_arg, arg_pos = _get_arg_context(text_before_cursor)

    # After -> operator, suggest functions
    if _after_arrow(text_before_cursor):
        functions = _get_available_functions()
        matches = _rank_matches(simple_token, functions)
        result = []
        for name in matches:
            if name in FUNCTIONS_WITH_ARGS:
                # Position cursor inside parentheses: pair(|)
                result.append((f"{name}()", -1))
            else:
                result.append((name, 0))
        return result

    # Inside a function call - context-aware completions
    if func:
        # Check for lens syntax: provider::
        if "::" in token:
            # User typed something like "claude::" or "claude::ar"
            parts = token.split("::", 1)
            provider = parts[0]
            lens_prefix = parts[1] if len(parts) > 1 else ""

            # Verify provider is valid
            providers = _get_available_providers()
            if provider in providers:
                lenses = _get_available_lenses()
                matches = _rank_matches(lens_prefix, lenses)
                # Return full provider::lens completions
                return [(f"{provider}::{lens}", 0) for lens in matches]

        # Check for model variant syntax: provider.
        if "." in token and "::" not in token:
            parts = token.split(".", 1)
            provider = parts[0]
            variant_prefix = parts[1] if len(parts) > 1 else ""

            providers = _get_available_providers()
            if provider in providers:
                variants = _get_model_variants(provider)
                matches = _rank_matches(variant_prefix, variants)
                # Return full provider.variant completions
                return [(f"{provider}.{variant}", 0) for variant in matches]

        # Check for keyword argument syntax: key:value
        if ":" in current_arg and "::" not in current_arg:
            # Already typing a kwarg value
            key_match = re.match(r"(\w+):\s*(.*)$", current_arg)
            if key_match:
                key = key_match.group(1).lower()
                value_prefix = key_match.group(2)

                # Suggest values based on the key
                if key == "eyes" or key == "lenses":
                    # Suggest lenses, supporting + syntax for multiple
                    if "+" in value_prefix:
                        # Already has some lenses, suggest more
                        used = set(v.strip().lower() for v in value_prefix.split("+") if v.strip())
                        all_lenses = _get_available_lenses()
                        remaining = [lens for lens in all_lenses if lens not in used]
                        # Get the part after the last +
                        last_plus = value_prefix.rfind("+")
                        after_plus = value_prefix[last_plus + 1:].strip()
                        matches = _rank_matches(after_plus, remaining)
                        # Return the full kwarg with added lens
                        prefix = value_prefix[:last_plus + 1]
                        return [(f"{key}:{prefix}{lens}", 0) for lens in matches]
                    else:
                        lenses = _get_available_lenses()
                        matches = _rank_matches(value_prefix, lenses)
                        return [(f"{key}:{lens}", 0) for lens in matches]
                elif key == "model" or key == "lead":
                    # Suggest providers
                    providers = _get_available_providers()
                    matches = _rank_matches(value_prefix, providers)
                    return [(f"{key}:{p}", 0) for p in matches]
                elif key == "fix":
                    # Boolean values
                    options = ["true", "false"]
                    matches = _rank_matches(value_prefix, options)
                    return [(f"{key}:{opt}", 0) for opt in matches]

        # Suggest keyword arguments if token looks like start of kwarg
        if func in FUNCTION_KWARGS:
            kwargs = FUNCTION_KWARGS[func]
            # If typing something that could be a kwarg name
            if simple_token and not any(c in token for c in [":", ".", "::"]):
                kwarg_matches = _rank_matches(simple_token, kwargs, show_all_on_empty=False)
                if kwarg_matches:
                    # Return kwarg: suggestions
                    return [(f"{kw}:", 0) for kw in kwarg_matches]

        # Function-specific first argument suggestions
        if arg_pos == 0 and not current_arg.strip():
            # Empty first argument - suggest based on function
            if func == "pair":
                # Suggest providers
                providers = _get_available_providers()
                return [(p, 0) for p in providers]
            elif func == "pride":
                # Suggest agent counts
                return [(x, 0) for x in PRIDE_SUGGESTIONS]
            elif func == "review":
                # Suggest self-heal operator
                return [("^", 0)]
            elif func in FUNCTION_KWARGS:
                # Suggest kwargs for this function
                kwargs = FUNCTION_KWARGS[func]
                return [(f"{kw}:", 0) for kw in kwargs]

        # Inside pair() first argument - suggest models
        if func == "pair" and arg_pos == 0:
            providers = _get_available_providers()
            matches = _rank_matches(simple_token, providers)
            result = []
            for p in matches:
                result.append((p, 0))
                # Also suggest common variants
                if not token or token == p:
                    for variant in _get_model_variants(p)[:2]:
                        result.append((f"{p}.{variant}", 0))
            return result

        # Inside pride() - suggest agent count or lenses kwarg
        if func == "pride":
            if arg_pos == 0:
                matches = [x for x in PRIDE_SUGGESTIONS if not simple_token or x.startswith(simple_token)]
                return [(m, 0) for m in matches]
            else:
                # Suggest lenses: kwarg
                if not simple_token or "lenses".startswith(simple_token):
                    return [("lenses:", 0)]

        # Inside review() - suggest self-heal operator
        if func == "review":
            if not simple_token or "^".startswith(simple_token):
                return [("^", 0)]

    # After a prompt or after a function call, suggest -> arrow
    # BUT only if the current syntax is valid
    if not token and (_has_prompt(text) or _ends_with_closed_paren(text)):
        if not text.endswith("->") and _is_valid_partial_pipeline(text):
            return [("-> ", 0)]

    # Show all functions if typing something that looks like start of pipeline
    if simple_token and not text_before_cursor.strip().startswith(":"):
        functions = _get_available_functions()
        matches = _rank_matches(simple_token, functions, show_all_on_empty=False)
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


def _is_in_prompt(text: str) -> bool:
    """Check if the cursor is still inside the prompt (before the first ->).

    The first segment of a Lion pipeline is always the prompt. No autocomplete
    should fire until the user has typed at least one -> operator.
    """
    # If there's no -> in the text at all, we're still in the prompt
    if "->" not in text:
        return True
    return False


def _find_first_arrow(text: str) -> int:
    """Find position of first -> that's outside quotes."""
    in_quote = False
    quote_char = None
    for i, ch in enumerate(text):
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
        elif ch == quote_char and in_quote:
            in_quote = False
            quote_char = None
        elif not in_quote and text[i:i+2] == "->":
            return i
    return -1


def get_pipeline_completions_for_readline(line_buffer: str, word: str) -> list[str]:
    """Get completions formatted for readline's word-based replacement.

    readline calls the completer with `word` = the current word being typed
    (determined by completer_delims). We return strings that will replace
    `word` in the line buffer.

    Args:
        line_buffer: The full line of text (readline.get_line_buffer())
        word: The current word readline identified for replacement

    Returns:
        List of strings to replace `word` with
    """
    text = line_buffer

    # --- Rule 1: No completions in the prompt part (before first ->) ---
    # Everything before the first -> is always the prompt (even if it looks
    # like a function call). Only offer `-> ` to start the pipeline.
    first_arrow = _find_first_arrow(text)
    if first_arrow == -1:
        before = text.rstrip()
        if word == "-":
            before = before.rstrip("-").rstrip()
        # Don't offer -> inside an unclosed quote (user is still typing the prompt string)
        if before:
            single_q = before.count("'") - before.count("\\'")
            double_q = before.count('"') - before.count('\\"')
            if single_q % 2 != 0 or double_q % 2 != 0:
                return []
        # Offer -> if there's any prompt text
        if before and (word == "-" or not word):
            return ["-> "]
        # Otherwise: still typing the prompt, no completions
        return []

    # --- Rule 2: Handle `-` -> `-> ` completion ---
    if word == "-":
        # Check if everything before the `-` is a valid pipeline
        before_dash = text[:text.rfind("-")].rstrip()
        if _is_valid_partial_pipeline(before_dash):
            return ["-> "]
        return []

    # --- Rule 3: After -> operator, suggest functions ---
    if _after_arrow(text):
        functions = _get_available_functions()
        matches = _rank_matches(word.lower(), functions)
        result = []
        for name in matches:
            if name in FUNCTIONS_WITH_ARGS:
                result.append(f"{name}(")
            else:
                result.append(name)
        return result

    # --- Rule 4: Inside a function call ---
    func = _get_current_function(text)
    if func:
        token = _extract_last_token(text)
        func_name, current_arg, arg_pos = _get_arg_context(text)

        # Lens syntax: provider::lens
        if "::" in token:
            parts = token.split("::", 1)
            provider = parts[0]
            lens_prefix = parts[1] if len(parts) > 1 else ""
            providers = _get_available_providers()
            if provider in providers:
                lenses = _get_available_lenses()
                matches = _rank_matches(lens_prefix, lenses)
                # word is the part after :: (since : is not a delim but
                # the token extraction handles it). Return full replacement.
                return [f"{provider}::{lens}" for lens in matches]

        # Model variant syntax: provider.variant
        if "." in token and "::" not in token:
            parts = token.split(".", 1)
            provider = parts[0]
            variant_prefix = parts[1] if len(parts) > 1 else ""
            providers = _get_available_providers()
            if provider in providers:
                variants = _get_model_variants(provider)
                matches = _rank_matches(variant_prefix, variants)
                # With delims including (, the word after ( is the full token
                # e.g. `pair(claude.h` -> word is `claude.h`
                return [f"{provider}.{v}" for v in matches]

        # Keyword argument: key:value
        if ":" in current_arg and "::" not in current_arg:
            key_match = re.match(r"(\w+):\s*(.*)$", current_arg)
            if key_match:
                key = key_match.group(1).lower()
                value_prefix = key_match.group(2)
                if key in ("eyes", "lenses"):
                    # Get the current segment (after last +)
                    if "+" in value_prefix:
                        plus_prefix = value_prefix[:value_prefix.rfind("+") + 1]
                        segment = value_prefix[value_prefix.rfind("+") + 1:].strip()
                    else:
                        plus_prefix = ""
                        segment = value_prefix

                    # Check for lens.provider or lens.provider.variant syntax
                    # e.g., arch.g -> arch.gemini, arch.gemini.f -> arch.gemini.flash
                    if "." in segment:
                        parts = segment.split(".")
                        lens_part = parts[0]
                        lenses = _get_available_lenses()
                        if lens_part.lower() in lenses:
                            providers = _get_available_providers()
                            if len(parts) == 2:
                                # lens.provider_prefix - suggest providers
                                provider_prefix = parts[1]
                                matches = _rank_matches(provider_prefix, providers)
                                return [f"{key}:{plus_prefix}{lens_part}.{p}" for p in matches]
                            elif len(parts) >= 3:
                                # lens.provider.variant_prefix - suggest model variants
                                provider = parts[1]
                                variant_prefix = ".".join(parts[2:])
                                if provider in providers:
                                    variants = _get_model_variants(provider)
                                    matches = _rank_matches(variant_prefix, variants)
                                    return [f"{key}:{plus_prefix}{lens_part}.{provider}.{v}" for v in matches]

                    # Plain lens completion
                    if "+" in value_prefix:
                        used = set(v.strip().split(".")[0].lower() for v in value_prefix.split("+") if v.strip())
                    else:
                        used = set()
                    all_lenses = _get_available_lenses()
                    remaining = [l for l in all_lenses if l not in used]
                    matches = _rank_matches(segment, remaining)
                    return [f"{key}:{plus_prefix}{l}" for l in matches]
                elif key in ("model", "lead"):
                    providers = _get_available_providers()
                    matches = _rank_matches(value_prefix, providers)
                    return [f"{key}:{p}" for p in matches]

        # Inside pair(): suggest providers and kwargs at any arg position
        # (pair args aren't strictly positional: pair(claude, eyes:arch) or pair(eyes:arch, claude))
        if func_name == "pair":
            if word:
                # Combine provider and kwarg matches
                providers = _get_available_providers()
                provider_matches = _rank_matches(word.lower(), providers, show_all_on_empty=False)
                kwargs = FUNCTION_KWARGS.get("pair", [])
                kw_matches = [f"{kw}:" for kw in _rank_matches(word.lower(), kwargs, show_all_on_empty=False)]
                combined = kw_matches + provider_matches
                if combined:
                    return combined
            else:
                # Empty word: suggest providers + kwargs
                providers = _get_available_providers()
                kwargs = [f"{kw}:" for kw in FUNCTION_KWARGS.get("pair", [])]
                return providers + kwargs

        # Suggest kwargs if word looks like start of one
        if func_name in FUNCTION_KWARGS and word:
            kwargs = FUNCTION_KWARGS[func_name]
            kw_matches = _rank_matches(word.lower(), kwargs, show_all_on_empty=False)
            if kw_matches:
                return [f"{kw}:" for kw in kw_matches]

        # Function-specific first argument
        if func_name == "pride" and arg_pos == 0:
            matches = [x for x in PRIDE_SUGGESTIONS if not word or x.startswith(word)]
            return matches

        if func_name == "review" and arg_pos == 0:
            if not word or "^".startswith(word):
                return ["^"]

        # Empty word inside function - suggest based on position
        if not word:
            if func_name == "pride":
                return PRIDE_SUGGESTIONS
            elif func_name == "review":
                return ["^"]
            elif func_name in FUNCTION_KWARGS:
                return [f"{kw}:" for kw in FUNCTION_KWARGS[func_name]]

    # --- Rule 5: After closed function or prompt, suggest -> ---
    stripped = text.rstrip()
    if not word and (_ends_with_closed_paren(stripped)):
        if _is_valid_partial_pipeline(stripped):
            return ["-> "]

    return []


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


# -- Syntax Highlighting for Lion Pipeline Syntax ----------------------------

try:
    from prompt_toolkit.lexers import Lexer
    from prompt_toolkit.document import Document
    from prompt_toolkit.formatted_text import FormattedText
    LEXER_AVAILABLE = True
except ImportError:
    Lexer = object  # type: ignore[assignment]
    Document = object  # type: ignore[assignment]
    FormattedText = object  # type: ignore[assignment]
    LEXER_AVAILABLE = False


# Token types for syntax highlighting
class TokenType:
    """Token types for Lion pipeline syntax."""
    STRING = "string"      # Quoted prompts
    ARROW = "arrow"        # -> and <-> operators
    FUNCTION = "function"  # Pipeline functions
    PROVIDER = "provider"  # claude, gemini, codex
    LENS = "lens"          # ::arch, ::sec, etc.
    NUMBER = "number"      # Agent counts
    KWARG = "kwarg"        # Keyword arguments
    OPERATOR = "operator"  # ^, +, etc.
    PAREN = "paren"        # ( and )
    INVALID = "invalid"    # Invalid tokens
    DEFAULT = "default"    # Everything else


# Color scheme for syntax highlighting
# Using ANSI color names compatible with prompt_toolkit
TOKEN_STYLES = {
    TokenType.STRING: "ansiyellow",
    TokenType.ARROW: "ansigreen bold",
    TokenType.FUNCTION: "ansicyan",
    TokenType.PROVIDER: "ansiblue",
    TokenType.LENS: "ansimagenta",
    TokenType.NUMBER: "ansicyan",
    TokenType.KWARG: "ansiwhite",
    TokenType.OPERATOR: "ansired bold",
    TokenType.PAREN: "ansiwhite",
    TokenType.INVALID: "ansired",
    TokenType.DEFAULT: "",
}


def tokenize_pipeline(text: str) -> list[tuple[str, str]]:
    """Tokenize a Lion pipeline string for syntax highlighting.

    Returns:
        List of (token_type, text) tuples
    """
    tokens = []
    i = 0
    functions = set(_get_available_functions())
    providers = set(_get_available_providers())
    lenses = set(_get_available_lenses())

    while i < len(text):
        # Skip whitespace
        if text[i].isspace():
            j = i
            while j < len(text) and text[j].isspace():
                j += 1
            tokens.append((TokenType.DEFAULT, text[i:j]))
            i = j
            continue

        # Quoted string
        if text[i] in ('"', "'"):
            quote = text[i]
            j = i + 1
            while j < len(text) and text[j] != quote:
                if text[j] == "\\" and j + 1 < len(text):
                    j += 2
                else:
                    j += 1
            if j < len(text):
                j += 1  # Include closing quote
            tokens.append((TokenType.STRING, text[i:j]))
            i = j
            continue

        # Arrow operators: ->, <->, <N->, =>
        if text[i:i+2] == "->":
            tokens.append((TokenType.ARROW, "->"))
            i += 2
            continue
        if text[i:i+3] == "<->":
            tokens.append((TokenType.ARROW, "<->"))
            i += 3
            continue
        if text[i:i+2] == "=>":
            tokens.append((TokenType.ARROW, "=>"))
            i += 2
            continue
        # <N-> pattern
        if text[i] == "<":
            match = re.match(r"<(\d*)->", text[i:])
            if match:
                tokens.append((TokenType.ARROW, match.group(0)))
                i += len(match.group(0))
                continue

        # Lens syntax: ::lens
        if text[i:i+2] == "::":
            j = i + 2
            while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                j += 1
            lens_name = text[i+2:j]
            if lens_name.lower() in lenses:
                tokens.append((TokenType.LENS, text[i:j]))
            else:
                tokens.append((TokenType.INVALID, text[i:j]))
            i = j
            continue

        # Parentheses
        if text[i] in "()":
            tokens.append((TokenType.PAREN, text[i]))
            i += 1
            continue

        # Special operators
        if text[i] in "^+,":
            tokens.append((TokenType.OPERATOR, text[i]))
            i += 1
            continue

        # Colon (kwarg separator)
        if text[i] == ":":
            tokens.append((TokenType.KWARG, ":"))
            i += 1
            continue

        # Identifier or number
        if text[i].isalnum() or text[i] in "_-.":
            j = i
            while j < len(text) and (text[j].isalnum() or text[j] in "_-."):
                j += 1
            word = text[i:j]
            word_lower = word.lower()

            # Determine token type
            if word.isdigit():
                tokens.append((TokenType.NUMBER, word))
            elif word_lower in functions:
                tokens.append((TokenType.FUNCTION, word))
            elif word_lower in providers or word_lower.split(".")[0] in providers:
                tokens.append((TokenType.PROVIDER, word))
            elif word_lower in lenses:
                tokens.append((TokenType.LENS, word))
            else:
                tokens.append((TokenType.DEFAULT, word))
            i = j
            continue

        # Unknown character
        tokens.append((TokenType.DEFAULT, text[i]))
        i += 1

    return tokens


def highlight_pipeline(text: str) -> str:
    """Return ANSI-colored string for terminal display.

    Uses the ANSI color codes from display.py for consistent coloring.
    """
    try:
        from ..display import GREEN, CYAN, YELLOW, RED, BLUE, RESET, BOLD, DIM
    except ImportError:
        # Fallback - no colors
        return text

    tokens = tokenize_pipeline(text)
    result = []

    for token_type, token_text in tokens:
        if token_type == TokenType.STRING:
            result.append(f"{YELLOW}{token_text}{RESET}")
        elif token_type == TokenType.ARROW:
            result.append(f"{GREEN}{BOLD}{token_text}{RESET}")
        elif token_type == TokenType.FUNCTION:
            result.append(f"{CYAN}{token_text}{RESET}")
        elif token_type == TokenType.PROVIDER:
            result.append(f"{BLUE}{token_text}{RESET}")
        elif token_type == TokenType.LENS:
            result.append(f"{DIM}{token_text}{RESET}")
        elif token_type == TokenType.NUMBER:
            result.append(f"{CYAN}{token_text}{RESET}")
        elif token_type == TokenType.OPERATOR:
            result.append(f"{RED}{BOLD}{token_text}{RESET}")
        elif token_type == TokenType.INVALID:
            result.append(f"{RED}{token_text}{RESET}")
        else:
            result.append(token_text)

    return "".join(result)


class LionLexer(Lexer):
    """Prompt-toolkit Lexer for Lion pipeline syntax highlighting.

    Provides real-time syntax highlighting as the user types:
    - Quoted prompts in yellow
    - Arrow operators (->, <->, =>) in green bold
    - Function names in cyan
    - Provider names in blue
    - Lens names in magenta
    - Numbers in cyan
    - Operators (^, +) in red bold
    - Invalid tokens in red
    """

    def lex_document(self, document):
        """Return a function that returns formatted text for each line."""
        text = document.text

        def get_line_tokens(line_no):
            """Get tokens for a specific line."""
            lines = text.split("\n")
            if line_no >= len(lines):
                return []

            line = lines[line_no]
            tokens = tokenize_pipeline(line)

            # Convert to prompt_toolkit format
            result = []
            for token_type, token_text in tokens:
                style = TOKEN_STYLES.get(token_type, "")
                result.append((style, token_text))

            return result

        return get_line_tokens


def get_lion_lexer():
    """Get a Lion syntax highlighter for prompt_toolkit.

    Returns None if prompt_toolkit is not available.
    """
    if not LEXER_AVAILABLE:
        return None
    return LionLexer()
