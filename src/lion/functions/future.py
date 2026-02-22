"""future() - Time-travel review function.

Evaluates code from the perspective of a developer N months/years in the future.
This provides insights on maintainability, scalability, and future pain points.
"""

import re
import time
from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display
from .self_heal import self_heal_loop, extract_critical_issues
from .utils import MAX_CODE_SIZE, get_current_code_from_disk


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

FIX_FUTURE_ISSUES_PROMPT = """You are an expert software engineer, brought from the future.
The user has provided a time-travel review with issues found in the codebase.

Your task is to fix ALL critical future pain points mentioned in the review.
Edit the files directly and be thorough.

FUTURE REVIEW:
{future_review_content}
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
    # Use step.self_heal as the single source of truth for ^ operator (set by parser)
    self_heal = step.self_heal if hasattr(step, 'self_heal') else False

    if step.args:
        # Args can be: future(6m), future(claude), future(6m, claude)
        # Skip ^ since it's handled by parser setting step.self_heal
        parsed_args = []
        for arg in step.args:
            arg_str = str(arg).strip().lower()
            if arg_str != "^":
                parsed_args.append(arg_str)

        if parsed_args:
            first_arg = parsed_args[0]
            if re.match(r'^\d+[mywdh]$', first_arg):
                time_arg = first_arg
                if len(parsed_args) > 1:
                    provider_name = parsed_args[1]
            elif re.match(r'^[a-zA-Z0-9\._-]+$', first_arg):
                provider_name = first_arg
                if len(parsed_args) > 1 and re.match(r'^\d+[mywdh]$', parsed_args[1]):
                    time_arg = parsed_args[1]

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

    # Truncate code if too large to avoid context overflow
    if len(code) > MAX_CODE_SIZE:
        code = code[:MAX_CODE_SIZE] + "\n\n... [CODE TRUNCATED - showing first 50KB] ..."

    future_prompt = FUTURE_PROMPT.format(
        time_period=time_period,
        code=code if code else "No code changes to review from future perspective.",
        decisions=decisions,
    )

    # Get max heal cost from config
    max_heal_cost = config.get("self_healing", {}).get("max_heal_cost")

    # State for the check function closure
    round_counter = [0]
    files_changed_state = [previous.get("files_changed", [])]

    def check_fn():
        """Run future review and return (passed, issues, content, tokens).

        On subsequent rounds, rebuilds the prompt from current disk state
        to ensure we're reviewing the actual fixed code, not stale data.
        """
        # On rounds > 0, get current code from disk instead of cached previous
        if round_counter[0] > 0:
            current_code = get_current_code_from_disk(cwd, files_changed_state[0])
            if current_code:
                current_prompt = FUTURE_PROMPT.format(
                    time_period=time_period,
                    code=current_code,
                    decisions=decisions,
                )
            else:
                current_prompt = future_prompt
        else:
            current_prompt = future_prompt

        Display.phase("future", f"Reviewing from {time_period} in the future (round {round_counter[0] + 1})...")

        start = time.time()
        result = provider.ask(current_prompt, "", cwd)
        duration = time.time() - start

        issues = _extract_future_concerns(result.content)
        critical_issues = extract_critical_issues(issues)

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
                "round": round_counter[0],
            },
        ))

        Display.notify(f"Future review round {round_counter[0] + 1}: Found {len(issues)} concerns ({len(critical_issues)} critical)")
        round_counter[0] += 1

        passed = len(critical_issues) == 0
        return passed, issues, result.content, result.tokens_used

    def fix_prompt_builder(content: str) -> str:
        """Build fix prompt from future review content."""
        return FIX_FUTURE_ISSUES_PROMPT.format(future_review_content=content)

    if self_heal:
        heal_result = self_heal_loop(
            check_fn=check_fn,
            fix_prompt_builder=fix_prompt_builder,
            provider=provider,
            cwd=cwd,
            max_rounds=2,
            max_cost=max_heal_cost,
            cost_manager=cost_manager,
            provider_name=provider_name,
            display_name="future",
            initial_files_changed=previous.get("files_changed", []),
        )

        issues = heal_result.issues
        critical_issues = extract_critical_issues(issues)
        warning_issues = [i for i in issues if i.get("severity") == "warning"]
        has_feedback = len(critical_issues) > 0 or len(warning_issues) > 0

        return {
            "success": True,
            "content": heal_result.content,
            "issues": issues,
            "critical_count": len(critical_issues),
            "warning_count": len(warning_issues),
            "suggestion_count": len([i for i in issues if i.get("severity") == "suggestion"]),
            "has_feedback": has_feedback,
            "errors_count": 0,
            "tokens_used": heal_result.total_tokens,
            "files_changed": heal_result.files_changed,
            "time_period": time_period,
            "future_review_passed": heal_result.passed,
        }
    else:
        # Non-self-healing: just run once
        passed, issues, content, tokens_used = check_fn()
        critical_issues = extract_critical_issues(issues)
        warning_issues = [i for i in issues if i.get("severity") == "warning"]
        has_feedback = len(critical_issues) > 0 or len(warning_issues) > 0

        # Track cost for non-self-heal path
        if cost_manager and tokens_used:
            cost_manager.add_cost(provider_name, tokens_used)

        return {
            "success": True,
            "content": content,
            "issues": issues,
            "critical_count": len(critical_issues),
            "warning_count": len(warning_issues),
            "suggestion_count": len([i for i in issues if i.get("severity") == "suggestion"]),
            "has_feedback": has_feedback,
            "errors_count": 0,
            "tokens_used": tokens_used,
            "files_changed": previous.get("files_changed", []),
            "time_period": time_period,
            "future_review_passed": len(critical_issues) == 0,
        }
