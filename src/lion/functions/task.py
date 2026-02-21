"""task() - Task decomposition for large features.

Splits a big task into smaller subtasks. Each subtask runs through
the rest of the pipeline independently.

Usage:
  task()     -- decompose into subtasks (max 5)
  task(10)   -- max 10 subtasks
  task(3)    -- max 3 subtasks

The AI analyzes the prompt and breaks it into concrete, implementable
subtasks. Each subtask then flows through whatever comes after task()
in the pipeline.
"""

import time

from ..memory import MemoryEntry
from ..providers import get_provider, is_provider_name
from ..display import Display


DECOMPOSE_PROMPT = """You are a software architect. Break down this task into concrete, implementable subtasks.

TASK: {prompt}

{context}

RULES:
1. Each subtask must be independently implementable
2. Each subtask should be small enough for a single agent to handle
3. Order subtasks by dependency (independent tasks first)
4. Maximum {max_tasks} subtasks
5. Be specific - include file paths, function names, etc.

OUTPUT FORMAT (strict - follow exactly):
SUBTASK 1: [short title]
DESCRIPTION: [1-3 sentences describing exactly what to build/change]
FILES: [comma-separated list of files to create/modify]
DEPENDS_ON: [comma-separated subtask numbers, or "none"]
PARALLEL: [yes/no - can this run in parallel with other independent tasks?]

SUBTASK 2: [short title]
DESCRIPTION: [...]
FILES: [...]
DEPENDS_ON: [...]
PARALLEL: [...]

... (continue for all subtasks)"""


def execute_task(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Decompose a large task into subtasks.

    Returns a list of subtasks that the pipeline executor will run
    through the remaining pipeline steps.
    """
    # Determine max tasks
    max_tasks = 5
    if step.args:
        first = step.args[0]
        if isinstance(first, int):
            max_tasks = max(1, min(first, 15))

    provider_name = config.get("providers", {}).get("default", "claude")

    # Check for explicit provider in args
    for arg in step.args:
        if isinstance(arg, str) and is_provider_name(arg):
            provider_name = arg

    provider = get_provider(provider_name, config)

    Display.phase("task", f"Decomposing into subtasks (max {max_tasks})...")

    # Build context from previous steps
    context = ""
    if previous.get("plan"):
        context += f"EXISTING PLAN:\n{previous['plan'][:5000]}\n\n"
    if previous.get("code"):
        context += f"EXISTING CODE CONTEXT:\n{previous['code'][:3000]}\n\n"
    if previous.get("deliberation_summary"):
        context += f"DELIBERATION:\n{previous['deliberation_summary'][:3000]}\n\n"

    decompose_prompt = DECOMPOSE_PROMPT.format(
        prompt=prompt,
        context=context,
        max_tasks=max_tasks,
    )

    start = time.time()
    result = provider.ask(decompose_prompt, "", cwd)
    duration = time.time() - start

    if not result.success:
        Display.step_error("task", result.error or "Decomposition failed")
        return {
            "success": False,
            "error": result.error,
            "files_changed": previous.get("files_changed", []),
            "tokens_used": result.tokens_used,
        }

    # Parse subtasks from output
    subtasks = _parse_subtasks(result.content, max_tasks)

    if not subtasks:
        Display.step_error("task", "Could not parse subtasks from response")
        return {
            "success": False,
            "error": "Failed to decompose task",
            "content": result.content,
            "files_changed": previous.get("files_changed", []),
            "tokens_used": result.tokens_used,
        }

    # Log to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="task",
        agent="decomposer",
        type="subtasks",
        content=result.content,
        metadata={
            "model": result.model,
            "subtask_count": len(subtasks),
            "max_tasks": max_tasks,
            "duration": duration,
        },
    ))

    # Display subtasks
    Display.notify(f"Decomposed into {len(subtasks)} subtasks:")
    for i, task in enumerate(subtasks):
        parallel_marker = " (parallel)" if task.get("parallel") else ""
        deps = task.get("depends_on", [])
        dep_str = f" [after: {', '.join(str(d) for d in deps)}]" if deps else ""
        Display.notify(f"  {i + 1}. {task['title']}{dep_str}{parallel_marker}")

    return {
        "success": True,
        "subtasks": subtasks,
        "content": result.content,
        "tokens_used": result.tokens_used,
        "files_changed": previous.get("files_changed", []),
        "is_task_decomposition": True,
    }


def _parse_subtasks(content, max_tasks):
    """Parse subtasks from AI output.

    Expected format:
    SUBTASK 1: title
    DESCRIPTION: ...
    FILES: ...
    DEPENDS_ON: ...
    PARALLEL: ...
    """
    subtasks = []
    current = None

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        upper = line.upper()

        # New subtask header
        if upper.startswith("SUBTASK ") and ":" in line:
            if current:
                subtasks.append(current)
                if len(subtasks) >= max_tasks:
                    break
            # Extract title after "SUBTASK N:"
            title = line.split(":", 1)[1].strip() if ":" in line else ""
            current = {
                "title": title,
                "description": "",
                "files": [],
                "depends_on": [],
                "parallel": False,
            }
        elif current:
            if upper.startswith("DESCRIPTION:"):
                current["description"] = line.split(":", 1)[1].strip()
            elif upper.startswith("FILES:"):
                files_str = line.split(":", 1)[1].strip()
                current["files"] = [
                    f.strip() for f in files_str.split(",") if f.strip()
                ]
            elif upper.startswith("DEPENDS_ON:") or upper.startswith("DEPENDS ON:"):
                deps_str = line.split(":", 1)[1].strip().lower()
                if deps_str and deps_str != "none":
                    current["depends_on"] = [
                        int(d.strip()) for d in deps_str.split(",")
                        if d.strip().isdigit()
                    ]
            elif upper.startswith("PARALLEL:"):
                val = line.split(":", 1)[1].strip().lower()
                current["parallel"] = val in ("yes", "true", "ja")

    # Don't forget the last subtask
    if current and len(subtasks) < max_tasks:
        subtasks.append(current)

    return subtasks
