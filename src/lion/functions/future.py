"""future() - Time-travel review function.

Evaluates code from the perspective of a developer N months/years in the future.
This provides insights on maintainability, scalability, and future pain points.
"""

import re
import time
from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display


FUTURE_PROMPT = """You are a developer working on this project {time_period} from now.
The code below was written today. You've been using it in production
since then.

CODE:
{code}

ARCHITECTURE DECISIONS:
{decisions}

From your future perspective, write about:

1. FRUSTRATIONS: What drives you crazy about this code now that
   you've been living with it? What do you wish they'd done differently?

2. MISSING FEATURES: What do stakeholders/users keep asking for
   that this code makes very hard to add?

3. SCALING ISSUES: What broke or became painful as usage grew?

4. MAINTENANCE BURDEN: What takes way too long to debug or update?

5. WHAT THEY GOT RIGHT: What are you grateful they thought of?

6. IF I COULD GO BACK: What specific changes would you tell the
   original developers to make right now, today, that would save
   you enormous pain in the future?

Be specific. Use concrete scenarios. Don't be vague.

Format your response as:
## Summary
[1-2 sentence overall assessment of the code's future-proofness]

## Issues Found
### [CRITICAL/WARNING/SUGGESTION] Issue Title
- **Category**: FRUSTRATION/MISSING_FEATURE/SCALING/MAINTENANCE
- **Problem**: description of the future pain point
- **Recommendation**: what should be changed now

## Positives
[What works well from a future perspective]

## Recommendations
[Prioritized list of changes to make now to prevent future pain]
"""


def _parse_time_period(time_arg: str) -> str:
    """Convert shorthand time notation to human-readable format.

    Examples:
        "6m" -> "6 months"
        "1y" -> "1 year"
        "3w" -> "3 weeks"
        "2d" -> "2 days"
    """
    if not time_arg:
        return "6 months"  # default

    time_arg = str(time_arg).strip().lower()

    # Match pattern like "6m", "1y", "3w", "2d"
    match = re.match(r'^(\d+)([mywdh])$', time_arg)
    if not match:
        # If no match, return as-is or default
        return time_arg if time_arg else "6 months"

    number = int(match.group(1))
    unit = match.group(2)

    unit_map = {
        'm': ('month', 'months'),
        'y': ('year', 'years'),
        'w': ('week', 'weeks'),
        'd': ('day', 'days'),
        'h': ('hour', 'hours'),
    }

    singular, plural = unit_map.get(unit, ('month', 'months'))
    return f"{number} {singular if number == 1 else plural}"


# Number of characters to search after issue header for category extraction
CATEGORY_LOOKAHEAD = 500


def _extract_future_concerns(content: str) -> list[dict]:
    """Extract structured concerns from future review content.

    Looks for patterns like:
    ### [CRITICAL] Issue Title
    ### [WARNING] Issue Title
    ### [SUGGESTION] Issue Title

    Returns list of dicts with severity, title, and category.
    """
    issues = []

    # Pattern to match issue headers
    pattern = r'###\s*\[?(CRITICAL|WARNING|SUGGESTION)\]?\s*(.+?)(?=\n|$)'
    matches = re.finditer(pattern, content, re.IGNORECASE)

    for match in matches:
        severity = match.group(1).lower()
        title = match.group(2).strip()

        # Try to extract category from the content following the header
        category = "general"
        category_pattern = r'\*\*Category\*\*:\s*(FRUSTRATION|MISSING_FEATURE|SCALING|MAINTENANCE)'
        # Search in the content after this match
        start_pos = match.end()
        remaining = content[start_pos:start_pos + CATEGORY_LOOKAHEAD]
        cat_match = re.search(category_pattern, remaining, re.IGNORECASE)
        if cat_match:
            category = cat_match.group(1).lower()

        issues.append({
            "severity": severity,
            "title": title,
            "category": category,
        })

    return issues


def execute_future(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute time-travel review from a future developer's perspective.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps (code, decisions, etc.)
        step: The PipelineStep with function name and args (e.g., future(6m))
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, content, issues, critical_count, warning_count, etc.
        Compatible with _needs_refinement() for <-> feedback loops.
    """
    # Defensive null check for previous
    previous = previous or {}

    # Get provider (default to claude, or use arg if specified after time period)
    provider_name = "claude"
    time_arg = "6m"  # default

    if step.args:
        first_arg = str(step.args[0])
        # Check if first arg is a time period (e.g., "6m", "1y")
        if re.match(r'^\d+[mywdh]$', first_arg):
            time_arg = first_arg
            # If there's a second arg, it's the provider
            if len(step.args) > 1:
                provider_name = str(step.args[1])
        else:
            # First arg might be the provider
            provider_name = first_arg

    provider = get_provider(provider_name, config)

    # Parse time period to human-readable format
    time_period = _parse_time_period(time_arg)

    # Extract code from previous steps
    code = previous.get("code", "")
    deliberation = previous.get("deliberation_summary", "")
    plan = previous.get("plan", "")

    # Build decisions context
    decisions_parts = []
    if plan:
        if len(plan) > 2000:
            decisions_parts.append(f"Plan:\n{plan[:2000]}...")
        else:
            decisions_parts.append(f"Plan:\n{plan}")
    if previous.get("final_decision"):
        decisions_parts.append(f"Decision: {previous['final_decision']}")
    if previous.get("decisions"):
        for d in previous["decisions"][:5]:  # Limit to 5 decisions
            decisions_parts.append(f"- {d[:200]}")
    decisions = "\n".join(decisions_parts) if decisions_parts else "No architectural decisions recorded."

    # Truncate code if too large (50KB limit to avoid context overflow)
    MAX_CODE_SIZE = 50000
    if len(code) > MAX_CODE_SIZE:
        code = code[:MAX_CODE_SIZE] + "\n\n... [CODE TRUNCATED - showing first 50KB] ..."

    future_prompt = FUTURE_PROMPT.format(
        time_period=time_period,
        code=code if code else "No code changes to review from future perspective.",
        decisions=decisions,
    )

    Display.phase("future", f"Reviewing from {time_period} in the future...")

    start = time.time()
    result = provider.ask(future_prompt, "", cwd)
    duration = time.time() - start

    # Track cost if manager provided
    if cost_manager and result.tokens_used:
        cost_manager.add_cost(provider_name, result.tokens_used)

    # Parse concerns from response
    issues = _extract_future_concerns(result.content)

    # Write to shared memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="future",
        agent="future_reviewer",
        type="future_review",
        content=result.content,
        metadata={
            "model": result.model,
            "time_period": time_period,
            "issues_count": len(issues),
            "duration": duration,
        },
    ))

    # Count issues by severity
    critical_issues = [i for i in issues if i.get("severity") == "critical"]
    warning_issues = [i for i in issues if i.get("severity") == "warning"]
    suggestion_issues = [i for i in issues if i.get("severity") == "suggestion"]

    # Determine if there's actionable feedback (for <-> operator)
    has_feedback = len(critical_issues) > 0 or len(warning_issues) > 0

    return {
        "success": result.success,
        "content": result.content,
        "issues": issues,
        "critical_count": len(critical_issues),
        "warning_count": len(warning_issues),
        "suggestion_count": len(suggestion_issues),
        "has_feedback": has_feedback,
        "errors_count": 0,  # Future review doesn't produce errors, just concerns
        "tokens_used": result.tokens_used,
        "files_changed": previous.get("files_changed", []),
        "time_period": time_period,
        "future_review_passed": len(critical_issues) == 0,
    }
