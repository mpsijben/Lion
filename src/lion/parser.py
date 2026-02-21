"""Parse lion input into prompt and pipeline steps.

Examples:
    "Build a feature"
        -> prompt="Build a feature", steps=[]

    "Build a feature" -> pride(3) -> review()
        -> prompt="Build a feature", steps=[Step("pride", [3]), Step("review", [])]

    "Build X" -> pride(claude, gemini)
        -> prompt="Build X", steps=[Step("pride", ["claude", "gemini"])]

    "Build X" -> pride(5) <-> review()
        -> feedback=True on review step (re-run producer with same agent count)

    "Build X" -> pride(5) <1-> review()
        -> feedback=True, feedback_agents=1 on review step (re-run producer with 1 agent)

    "Build X" -> pride(claude::arch, gemini::sec)
        -> Lens syntax: provider::lens stored as "provider::lens" string in args

    "Build X" -> pride(3, lenses: auto)
        -> Auto-assign lenses based on task content
"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineStep:
    function: str       # e.g. "pride", "review", "devil"
    args: list[Any] = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    feedback: bool = False          # True if preceded by <-> or <N->
    feedback_agents: int | None = None  # Override agent count for re-run (None = use original)


def parse_lion_input(raw: str, config: dict = None) -> tuple[str, list[PipelineStep]]:
    """Parse raw lion input into prompt and pipeline steps."""
    config = config or {}

    # Extract the quoted prompt first, then treat the rest as pipeline.
    # This prevents -> inside the prompt text from being parsed as pipeline separators.
    prompt, pipeline_str = _split_prompt_and_pipeline(raw)

    if not pipeline_str:
        return prompt, []

    # Split pipeline on -> and <-> / <N-> while preserving the delimiter.
    # Matches: ->, <->, <1->, <3->, etc.
    tokens = re.split(r"\s*(<\d*->|->)\s*", pipeline_str)

    # tokens alternates: [step, delimiter, step, delimiter, step, ...]
    # Even indices are step strings, odd indices are delimiters.
    steps = []
    for idx in range(0, len(tokens), 2):
        step_str = tokens[idx].strip()
        if not step_str:
            continue

        step = _parse_step(step_str, config)
        if not step:
            continue

        # Check if the delimiter before this step was a feedback operator
        if idx > 0:
            delimiter = tokens[idx - 1]
            feedback_match = re.match(r"<(\d*)->", delimiter)
            if feedback_match:
                step.feedback = True
                agent_str = feedback_match.group(1)
                step.feedback_agents = int(agent_str) if agent_str else None

        steps.append(step)

    return prompt, steps


def _split_prompt_and_pipeline(raw: str) -> tuple[str, str]:
    """Split raw input into prompt and pipeline string, respecting quotes.

    The prompt is either:
    - A quoted string ("..." or '...') followed by optional -> pipeline
    - Everything before the first -> that looks like a pipeline step (word with optional parens)
    """
    raw = raw.strip()

    # Case 1: Prompt starts with a quote character
    if raw and raw[0] in ('"', "'"):
        quote_char = raw[0]
        # Find the matching closing quote
        end = raw.find(quote_char, 1)
        if end != -1:
            prompt = raw[1:end]
            rest = raw[end + 1:].strip()
            # Strip leading -> from the pipeline part
            if rest.startswith("->"):
                return prompt, rest[2:].strip()
            return prompt, ""

    # Case 2: No quotes -- find the first -> or <-> followed by a valid function name
    # Valid function looks like: word or word() or word(args)
    for match in re.finditer(r"\s*(?:<\d*->|->)\s*", raw):
        rest_after = raw[match.end():].strip()
        # Check if what follows looks like a pipeline step (starts with a word char)
        if re.match(r"[a-zA-Z_]\w*", rest_after):
            prompt = raw[:match.start()].strip().strip('"').strip("'")
            return prompt, rest_after

    # No pipeline found
    prompt = raw.strip().strip('"').strip("'")
    return prompt, ""


def _parse_step(step_str: str, config: dict) -> PipelineStep:
    """Parse a single pipeline step like 'pride(3)' or 'review(claude)'."""

    # Check if it's a saved pattern
    patterns = config.get("patterns", {})
    pattern_name = step_str.rstrip("()")
    if pattern_name in patterns:
        pattern_pipeline = patterns[pattern_name]
        _, pattern_steps = parse_lion_input(f'"_" -> {pattern_pipeline}', config)
        return PipelineStep(
            function="__pattern__",
            args=pattern_steps,
            kwargs={"name": pattern_name},
        )

    # Parse function name and arguments
    match = re.match(r"(\w+)\((.*?)\)", step_str)
    if not match:
        return PipelineStep(function=step_str.lower())

    func_name = match.group(1).lower()
    args_str = match.group(2).strip()

    if not args_str:
        return PipelineStep(function=func_name)

    # Parse arguments
    args = []
    kwargs = {}

    for arg in _split_args(args_str):
        arg = arg.strip()
        # IMPORTANT: Check for :: (lens syntax) BEFORE checking for single : (kwargs)
        # This ensures "claude::arch" is treated as a lens-provider pair, not a kwarg
        if "::" in arg:
            # Lens syntax: provider::lens - store as string for downstream processing
            args.append(arg)
        elif ":" in arg and not arg.startswith('"'):
            # Kwarg syntax: key: value
            key, value = arg.split(":", 1)
            kwargs[key.strip()] = _parse_value(value.strip())
        else:
            args.append(_parse_value(arg))

    return PipelineStep(function=func_name, args=args, kwargs=kwargs)


def _split_args(args_str: str) -> list[str]:
    """Split comma-separated args, respecting brackets and quotes."""
    args = []
    depth = 0
    current = ""
    in_quotes = False

    for char in args_str:
        if char == '"':
            in_quotes = not in_quotes
        elif char in "([" and not in_quotes:
            depth += 1
        elif char in ")]" and not in_quotes:
            depth -= 1
        elif char == "," and depth == 0 and not in_quotes:
            args.append(current)
            current = ""
            continue
        current += char

    if current.strip():
        args.append(current)

    return args


def _parse_value(value: str) -> Any:
    """Parse a value string into appropriate type."""
    value = value.strip().strip('"').strip("'")

    # Integer
    try:
        return int(value)
    except ValueError:
        pass

    # Duration (e.g. "6m", "1y")
    if re.match(r"^\d+[mywdh]$", value):
        return value

    # List (e.g. [architect, builder])
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].split(",")
        return [item.strip().strip('"') for item in items]

    # String (provider name, branch name, etc.)
    return value


def parse_lens_arg(arg: str) -> tuple[str, str | None]:
    """Parse a potential lens argument into (provider, lens) tuple.

    Args:
        arg: An argument string, possibly containing :: lens syntax

    Returns:
        Tuple of (provider, lens) where lens is None if no :: present

    Examples:
        >>> parse_lens_arg("claude::arch")
        ("claude", "arch")
        >>> parse_lens_arg("claude")
        ("claude", None)
        >>> parse_lens_arg("gemini::security")
        ("gemini", "security")
    """
    if isinstance(arg, str) and "::" in arg:
        parts = arg.split("::", 1)
        return (parts[0].strip(), parts[1].strip())
    return (str(arg), None)


def has_lens_syntax(args: list) -> bool:
    """Check if any argument contains lens syntax (::).

    Args:
        args: List of parsed arguments

    Returns:
        True if any argument contains ::
    """
    return any(isinstance(arg, str) and "::" in arg for arg in args)
