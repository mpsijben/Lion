"""devil() - Devil's advocate / contrarian function.

Challenges architectural decisions and assumptions. Does NOT look for bugs
(that's review()) -- instead challenges the DECISIONS and ASSUMPTIONS made
by the team.
"""

import re
import time
from ..memory import SharedMemory, MemoryEntry
from ..providers import get_provider, is_provider_name
from ..display import Display
from ..toon import encode as toon_encode
from .self_heal import self_heal_loop, extract_critical_issues
from .utils import MAX_CODE_SIZE, get_current_code_from_disk


DEVIL_PROMPT = """You are the Devil's Advocate. Your job is NOT to find bugs
(the review agent does that). Your job is to challenge the
DECISIONS and ASSUMPTIONS made by the team.

THE TEAM'S APPROACH:
{consensus_plan}

THE CODE THEY WROTE:
{code}

Challenge their work on these dimensions:
1. ASSUMPTIONS: What are they assuming that might not be true?
   (e.g., "they assume low traffic, but what if it 10x's")

2. ARCHITECTURE: Will this design scale? Is it the right pattern?
   Are they going to regret this choice in 6 months?

3. ALTERNATIVES: What approach did they NOT consider that might
   be fundamentally better?

4. DEPENDENCIES: Are they depending on something fragile?

5. OVER-ENGINEERING: Are they building too much? Could this be
   simpler?

6. UNDER-ENGINEERING: Are they cutting corners that will hurt?

For each challenge:
- State the assumption or decision you're challenging
- Explain WHY it's risky
- Propose a concrete alternative
- Rate severity: CRITICAL (rethink now) / WARNING (consider) / SUGGESTION (minor concern)

Be genuinely adversarial. Don't softball it. If the approach is
actually solid, say so -- but really try to break it first.

Format your response as:
## Summary
[1-2 sentence overall assessment]

## Issues Found
### [CRITICAL/WARNING/SUGGESTION] Issue Title
- **Category**: ASSUMPTION/ARCHITECTURE/ALTERNATIVE/DEPENDENCY/OVER_ENGINEERING/UNDER_ENGINEERING
- **Problem**: what's risky about this decision
- **Alternative**: concrete alternative approach

## Verdict
[Overall assessment: is this approach fundamentally sound or does it need rethinking?]
"""

DEVIL_AGGRESSIVE_PROMPT = """You are an AGGRESSIVE Devil's Advocate. Your mission is to
absolutely tear apart the team's approach. Assume everything will fail.
Assume the worst case for every decision. Be ruthless but constructive.

THE TEAM'S APPROACH:
{consensus_plan}

THE CODE THEY WROTE:
{code}

Attack on EVERY dimension:
1. ASSUMPTIONS: What hidden assumptions will blow up in production?
2. ARCHITECTURE: Why is this the WRONG architecture?
3. ALTERNATIVES: What obviously better approach did they miss?
4. DEPENDENCIES: What will break first?
5. OVER-ENGINEERING: What's unnecessary complexity?
6. UNDER-ENGINEERING: What corners are being cut?
7. SECURITY: What attack vectors does this open?
8. SCALABILITY: At what point does this completely fall over?

For each challenge:
- State the assumption or decision you're challenging
- Explain WHY it will fail (not "might fail" -- WILL fail)
- Propose a concrete alternative
- Rate severity: CRITICAL (rethink now) / WARNING (consider) / SUGGESTION (minor concern)

Be brutal. If the approach is actually perfect (unlikely), grudgingly admit it.

Format your response as:
## Summary
[1-2 sentence overall assessment]

## Issues Found
### [CRITICAL/WARNING/SUGGESTION] Issue Title
- **Category**: ASSUMPTION/ARCHITECTURE/ALTERNATIVE/DEPENDENCY/OVER_ENGINEERING/UNDER_ENGINEERING/SECURITY/SCALABILITY
- **Problem**: what's risky about this decision
- **Alternative**: concrete alternative approach

## Verdict
[Overall assessment: is this approach fundamentally sound or does it need rethinking?]
"""

FIX_DEVIL_ISSUES_PROMPT = """You are an expert software engineer.
The user has provided a devil's advocate review with challenges found in the codebase.

Your task is to address ALL critical challenges mentioned in the review.
Edit the files directly and be thorough.

DEVIL'S ADVOCATE REVIEW:
{devil_review_content}
"""


def execute_devil(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute devil's advocate challenge on previous step output.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps (code, decisions, etc.)
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success, content, issues, critical_count, warning_count, etc.
        Compatible with _needs_refinement() for <-> feedback loops.
    """
    previous = previous or {}

    # Get provider and mode from args
    provider_name = "claude"
    aggressive = False
    # Use step.self_heal as the single source of truth for ^ operator (set by parser)
    self_heal = step.self_heal if hasattr(step, 'self_heal') else False

    for arg in (step.args or []):
        arg_str = str(arg).lower()
        if arg_str == "aggressive":
            aggressive = True
        # Skip ^ since it's handled by parser setting step.self_heal
        elif arg_str != "^" and is_provider_name(arg_str):
            provider_name = arg_str

    provider = get_provider(provider_name, config)

    # Extract code and plan from previous steps
    code = previous.get("code", "")
    deliberation = previous.get("deliberation_summary", "")
    plan = previous.get("plan", "")

    # Build consensus plan context
    plan_parts = []
    if plan:
        if len(plan) > 2000:
            plan_parts.append(f"Plan:\n{plan[:2000]}...")
        else:
            plan_parts.append(f"Plan:\n{plan}")
    if previous.get("final_decision"):
        plan_parts.append(f"Decision: {previous['final_decision']}")
    if deliberation:
        if len(deliberation) > 2000:
            plan_parts.append(f"Deliberation:\n{deliberation[:2000]}...")
        else:
            plan_parts.append(f"Deliberation:\n{deliberation}")
    consensus_plan = "\n".join(plan_parts) if plan_parts else "No plan or decisions recorded."

    # Truncate code if too large to avoid context overflow
    if len(code) > MAX_CODE_SIZE:
        code = code[:MAX_CODE_SIZE] + "\n\n... [CODE TRUNCATED - showing first 50KB] ..."

    # Select prompt template based on mode
    template = DEVIL_AGGRESSIVE_PROMPT if aggressive else DEVIL_PROMPT
    devil_prompt = template.format(
        consensus_plan=consensus_plan,
        code=code if code else "No code changes to challenge.",
    )

    # Get max heal cost from config
    max_heal_cost = config.get("self_healing", {}).get("max_heal_cost")

    # State for the check function closure
    round_counter = [0]
    mode_str = "aggressively " if aggressive else ""
    files_changed_state = [previous.get("files_changed", [])]

    def check_fn():
        """Run devil's advocate and return (passed, issues, content, tokens).

        On subsequent rounds, rebuilds the prompt from current disk state
        to ensure we're reviewing the actual fixed code, not stale data.
        """
        # On rounds > 0, get current code from disk instead of cached previous
        if round_counter[0] > 0:
            current_code = get_current_code_from_disk(cwd, files_changed_state[0])
            if current_code:
                current_prompt = template.format(
                    consensus_plan=consensus_plan,
                    code=current_code,
                )
            else:
                current_prompt = devil_prompt
        else:
            current_prompt = devil_prompt

        Display.phase("devil", f"{mode_str}Challenging decisions and assumptions (round {round_counter[0] + 1})...")

        start = time.time()
        result = provider.ask(current_prompt, "", cwd)
        duration = time.time() - start

        issues = _extract_challenges(result.content)
        critical_issues = extract_critical_issues(issues)

        # Write to shared memory with TOON-encoded issues for compact context
        if issues:
            issues_toon = toon_encode({"issues": issues})
            compact_content = f"{issues_toon}\n\nFull analysis:\n{result.content[:3000]}"
        else:
            compact_content = result.content[:3000]

        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="devil",
            agent="devil_advocate",
            type="devil_review",
            content=compact_content,
            metadata={
                "model": result.model,
                "aggressive": aggressive,
                "issues_count": len(issues),
                "duration": duration,
                "round": round_counter[0],
            },
        ))

        Display.notify(f"Devil's Advocate round {round_counter[0] + 1}: Found {len(issues)} challenges ({len(critical_issues)} critical)")
        round_counter[0] += 1

        passed = len(critical_issues) == 0
        return passed, issues, result.content, result.tokens_used

    def fix_prompt_builder(content: str) -> str:
        """Build fix prompt from devil's advocate content."""
        return FIX_DEVIL_ISSUES_PROMPT.format(devil_review_content=content)

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
            display_name="devil",
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
            "devil_passed": heal_result.passed,
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
            "devil_passed": len(critical_issues) == 0,
        }


# Number of characters to search after issue header for category extraction
CATEGORY_LOOKAHEAD = 500


def _extract_challenges(content: str) -> list[dict]:
    """Extract structured challenges from devil's advocate content.

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
        category_pattern = (
            r'\*\*Category\*\*:\s*'
            r'(ASSUMPTION|ARCHITECTURE|ALTERNATIVE|DEPENDENCY|'
            r'OVER_ENGINEERING|UNDER_ENGINEERING|SECURITY|SCALABILITY)'
        )
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
