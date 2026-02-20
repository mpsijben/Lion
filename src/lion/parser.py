"""Parse lion input into prompt and pipeline steps.

Examples:
    "Build a feature"
        -> prompt="Build a feature", steps=[]

    "Build a feature" -> pride(3) -> review()
        -> prompt="Build a feature", steps=[Step("pride", [3]), Step("review", [])]

    "Build X" -> pride(claude, gemini)
        -> prompt="Build X", steps=[Step("pride", ["claude", "gemini"])]
"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineStep:
    function: str       # e.g. "pride", "review", "devil"
    args: list[Any] = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)


def parse_lion_input(raw: str, config: dict = None) -> tuple[str, list[PipelineStep]]:
    """Parse raw lion input into prompt and pipeline steps."""
    config = config or {}

    # Split on " -> " to separate prompt from pipeline
    parts = re.split(r"\s*->\s*", raw, maxsplit=1)

    prompt = parts[0].strip().strip('"').strip("'")

    if len(parts) < 2:
        return prompt, []

    pipeline_str = parts[1]

    # Split remaining on " -> "
    step_strings = re.split(r"\s*->\s*", pipeline_str)

    steps = []
    for step_str in step_strings:
        step_str = step_str.strip()
        if not step_str:
            continue

        step = _parse_step(step_str, config)
        if step:
            steps.append(step)

    return prompt, steps


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
        return PipelineStep(function=step_str)

    func_name = match.group(1)
    args_str = match.group(2).strip()

    if not args_str:
        return PipelineStep(function=func_name)

    # Parse arguments
    args = []
    kwargs = {}

    for arg in _split_args(args_str):
        arg = arg.strip()
        if ":" in arg and not arg.startswith('"'):
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
