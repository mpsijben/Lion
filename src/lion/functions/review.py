"""review() - Code review function.

Reviews code changes from previous pipeline steps for bugs, style issues,
and suggests improvements using claude -p.
"""

import re
import time
from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display
from ..toon import encode as toon_encode
from .self_heal import self_heal_loop, extract_critical_issues
from .utils import MAX_CODE_SIZE, get_current_code_from_disk


REVIEW_PROMPT = """Review the following code changes for:
1. Bugs and logic errors
2. Error handling completeness
3. Code style consistency with the existing codebase
4. Performance concerns
5. Missing edge cases

CODE CHANGES:
{code}

CONTEXT (what was built):
{context}

For each issue found, specify:
- Severity (critical / warning / suggestion)
- File and approximate location
- The problem
- Suggested fix

If issues are critical, provide the corrected code.

Format your response as:
## Summary
[1-2 sentence overall assessment]

## Issues Found
### [CRITICAL/WARNING/SUGGESTION] Issue Title
- **Location**: file/function
- **Problem**: description
- **Fix**: suggested solution

## Recommendations
[Any general recommendations for improvement]
"""

FIX_ISSUES_PROMPT = """You are an expert software engineer.
The user has provided a code review with issues found in the codebase.

Your task is to fix ALL issues mentioned in the review.
Edit the files directly and be thorough.

REVIEW:
{review_content}
"""


def execute_review(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute code review on previous step output.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps (code, files_changed, etc.)
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, content, issues, tokens_used, etc.
    """
    # Defensive null check for previous
    previous = previous or {}

    # Get provider (default to claude, or use arg if specified)
    provider_name = "claude"
    # Use step.self_heal as the single source of truth for ^ operator (set by parser)
    self_heal = step.self_heal if hasattr(step, 'self_heal') else False

    if step.args:
        for arg in step.args:
            arg_str = str(arg)
            # Skip ^ since it's handled by parser setting step.self_heal
            if arg_str != "^":
                provider_name = arg_str

    provider = get_provider(provider_name, config)

    # Extract code from previous steps
    code = previous.get("code", "")
    plan = previous.get("plan", "")

    # Build context from available info
    context_parts = []
    if plan:
        if len(plan) > 500:
            context_parts.append(f"Plan: {plan[:500]}...")
        else:
            context_parts.append(f"Plan: {plan}")
    if previous.get("final_decision"):
        context_parts.append(f"Decision: {previous['final_decision']}")
    context = "\n".join(context_parts) if context_parts else "No additional context available."

    # Truncate code if too large to avoid context overflow
    if len(code) > MAX_CODE_SIZE:
        code = code[:MAX_CODE_SIZE] + "\n\n... [CODE TRUNCATED - showing first 50KB] ..."

    review_prompt = REVIEW_PROMPT.format(
        code=code if code else "No code changes to review.",
        context=context,
    )

    Display.phase("review", "Reviewing code for issues...")

    # Get max heal cost from config
    max_heal_cost = config.get("self_healing", {}).get("max_heal_cost")

    # State for the check function closure
    last_result = {"content": "", "issues": [], "model": ""}
    round_counter = [0]
    files_changed_state = [previous.get("files_changed", [])]

    def check_fn():
        """Run review and return (passed, issues, content, tokens).

        On subsequent rounds, rebuilds the prompt from current disk state
        to ensure we're reviewing the actual fixed code, not stale data.
        """
        # On rounds > 0, get current code from disk instead of cached previous
        if round_counter[0] > 0:
            current_code = get_current_code_from_disk(cwd, files_changed_state[0])
            if current_code:
                current_prompt = REVIEW_PROMPT.format(
                    code=current_code,
                    context=context,
                )
            else:
                current_prompt = review_prompt
        else:
            current_prompt = review_prompt

        start = time.time()
        result = provider.ask(current_prompt, "", cwd)
        duration = time.time() - start

        issues = _extract_issues(result.content)
        critical_issues = extract_critical_issues(issues)

        # Store for memory logging
        last_result["content"] = result.content
        last_result["issues"] = issues
        last_result["model"] = result.model

        # Write to shared memory with TOON-encoded issues for compact context
        if issues:
            issues_toon = toon_encode({"issues": issues})
            compact_content = f"{issues_toon}\n\nFull review:\n{result.content[:3000]}"
        else:
            compact_content = result.content[:3000]

        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="review",
            agent="reviewer",
            type="review",
            content=compact_content,
            metadata={
                "model": result.model,
                "issues_count": len(issues),
                "duration": duration,
                "round": round_counter[0],
            },
        ))

        Display.notify(f"Review round {round_counter[0] + 1}: Found {len(issues)} issues ({len(critical_issues)} critical)")
        round_counter[0] += 1

        passed = len(critical_issues) == 0
        return passed, issues, result.content, result.tokens_used

    def fix_prompt_builder(content: str) -> str:
        """Build fix prompt from review content."""
        return FIX_ISSUES_PROMPT.format(review_content=content)

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
            display_name="review",
            initial_files_changed=previous.get("files_changed", []),
        )

        issues = heal_result.issues
        critical_issues = extract_critical_issues(issues)

        return {
            "success": True,
            "content": heal_result.content,
            "issues": issues,
            "critical_count": len(critical_issues),
            "warning_count": len([i for i in issues if i.get("severity") == "warning"]),
            "suggestion_count": len([i for i in issues if i.get("severity") == "suggestion"]),
            "tokens_used": heal_result.total_tokens,
            "files_changed": heal_result.files_changed,
            "review_passed": heal_result.passed,
        }
    else:
        # Non-self-healing: just run once
        passed, issues, content, tokens_used = check_fn()
        critical_issues = extract_critical_issues(issues)

        # Track cost for non-self-heal path
        if cost_manager and tokens_used:
            cost_manager.add_cost(provider_name, tokens_used)

        return {
            "success": True,
            "content": content,
            "issues": issues,
            "critical_count": len(critical_issues),
            "warning_count": len([i for i in issues if i.get("severity") == "warning"]),
            "suggestion_count": len([i for i in issues if i.get("severity") == "suggestion"]),
            "tokens_used": tokens_used,
            "files_changed": previous.get("files_changed", []),
            "review_passed": len(critical_issues) == 0,
        }


def _extract_issues(content: str) -> list[dict]:
    """Extract structured issues from review content.

    Looks for patterns like:
    ### [CRITICAL] Issue Title
    ### [WARNING] Issue Title
    ### [SUGGESTION] Issue Title
    """
    issues = []

    # Pattern to match issue headers
    pattern = r'###\s*\[?(CRITICAL|WARNING|SUGGESTION)\]?\s*(.+?)(?=\n|$)'
    matches = re.finditer(pattern, content, re.IGNORECASE)

    for match in matches:
        severity = match.group(1).lower()
        title = match.group(2).strip()
        issues.append({
            "severity": severity,
            "title": title,
        })

    return issues
