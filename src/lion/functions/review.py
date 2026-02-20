"""review() - Code review function.

Reviews code changes from previous pipeline steps for bugs, style issues,
and suggests improvements using claude -p.
"""

import time
from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider
from ..display import Display


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
    # Get provider (default to claude, or use arg if specified)
    provider_name = "claude"
    if step.args:
        provider_name = str(step.args[0])
    
    provider = get_provider(provider_name, config)
    
    # Extract code from previous steps
    code = previous.get("code", "")
    deliberation = previous.get("deliberation_summary", "")
    plan = previous.get("plan", "")
    
    # Build context from available info
    context_parts = []
    if plan:
        context_parts.append(f"Plan: {plan[:500]}...") if len(plan) > 500 else context_parts.append(f"Plan: {plan}")
    if previous.get("final_decision"):
        context_parts.append(f"Decision: {previous['final_decision']}")
    context = "\n".join(context_parts) if context_parts else "No additional context available."
    
    # Truncate code if too large (50KB limit to avoid context overflow)
    MAX_CODE_SIZE = 50000
    if len(code) > MAX_CODE_SIZE:
        code = code[:MAX_CODE_SIZE] + "\n\n... [CODE TRUNCATED - showing first 50KB] ..."
    
    review_prompt = REVIEW_PROMPT.format(
        code=code if code else "No code changes to review.",
        context=context,
    )
    
    Display.phase("review", "Reviewing code for issues...")
    
    start = time.time()
    result = provider.ask(review_prompt, "", cwd)
    duration = time.time() - start
    
    # Track cost if manager provided
    if cost_manager and result.tokens_used:
        cost_manager.add_cost(provider_name, result.tokens_used)
    
    # Parse issues from response (simple extraction)
    issues = _extract_issues(result.content)
    
    # Write to shared memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="review",
        agent="reviewer",
        type="review",
        content=result.content,
        metadata={
            "model": result.model,
            "issues_count": len(issues),
            "duration": duration,
        },
    ))
    
    # Determine if there are critical issues
    critical_issues = [i for i in issues if i.get("severity") == "critical"]
    
    return {
        "success": result.success,
        "content": result.content,
        "issues": issues,
        "critical_count": len(critical_issues),
        "warning_count": len([i for i in issues if i.get("severity") == "warning"]),
        "suggestion_count": len([i for i in issues if i.get("severity") == "suggestion"]),
        "tokens_used": result.tokens_used,
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
    import re
    
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
