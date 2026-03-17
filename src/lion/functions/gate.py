"""gate() - Human-in-the-loop pipeline gate.

Pauses the pipeline and shows the current output for review.
The user can approve, provide feedback (triggers a plan revision),
or abort the pipeline.

Usage in pipeline:
    "Build auth" -> fuse(3) -> gate() -> impl()
    "Build API" -> pride(3) -> gate() -> test()
"""

import time

from ..display import Display
from ..escalation import _read_tty, _print_tty
from ..memory import MemoryEntry
from ..providers import get_provider


REVISE_PROMPT = """You are revising a plan based on human feedback.

ORIGINAL PLAN:
{plan}

HUMAN FEEDBACK:
{feedback}

Rewrite the plan incorporating the feedback. Keep everything that wasn't
addressed by the feedback. Output the complete revised plan -- not just
the changes.

Start directly with the revised plan."""


def _show_previous(previous):
    """Display a summary of the previous step's output."""
    if not previous:
        _print_tty("   (no output from previous step)")
        return

    # Show plan if available
    plan = previous.get("plan", "")
    if plan:
        _print_tty("")
        for line in plan.splitlines():
            _print_tty(f"   {line}")
        _print_tty("")
        return

    # Show final_decision as fallback
    decision = previous.get("final_decision", "")
    if decision:
        _print_tty(f"\n   {decision}\n")
        return

    # Show content as last resort
    content = previous.get("content", "")
    if content:
        for line in content.splitlines():
            _print_tty(f"   {line}")
        _print_tty("")
        return

    _print_tty("   (previous step produced no displayable output)")


def _revise_plan(previous, feedback, config, cwd):
    """Use an LLM to revise the plan with user feedback."""
    provider_name = config.get("providers", {}).get("default", "claude")
    provider = get_provider(provider_name, config)

    plan = previous.get("plan", previous.get("final_decision", previous.get("content", "")))

    revise_prompt = REVISE_PROMPT.format(plan=plan, feedback=feedback)
    result = provider.ask(revise_prompt, "", cwd)

    if result.success:
        return result.content
    return None


def execute_gate(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute gate() - pause pipeline for human review.

    Args:
        prompt: The original user prompt
        previous: Dict with output from previous steps
        step: The PipelineStep with function name and args
        memory: SharedMemory instance for logging
        config: Lion configuration dict
        cwd: Working directory
        cost_manager: Optional cost tracking manager

    Returns:
        dict with success and (possibly revised) previous output
    """
    Display.phase("gate", "Waiting for human review...")

    _show_previous(previous)

    _print_tty("   [Enter] continue  |  [text] revise plan  |  [q] abort")
    user_input = _read_tty("   > ")

    # Abort
    if user_input.lower() in ("q", "quit", "exit"):
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="gate",
            agent="human",
            type="abort",
            content="Pipeline aborted by user at gate",
        ))
        return {
            "success": False,
            "error": "Pipeline aborted by user",
            "aborted": True,
        }

    # Pass through
    if not user_input:
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="gate",
            agent="human",
            type="approve",
            content="User approved output without changes",
        ))
        Display.phase("gate", "Approved - continuing pipeline")
        result = dict(previous) if previous else {"success": True}
        result["success"] = True
        return result

    # Revise plan with feedback
    Display.phase("gate", "Revising plan with your feedback...")

    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="gate",
        agent="human",
        type="feedback",
        content=user_input,
    ))

    revised = _revise_plan(previous, user_input, config, cwd)

    if revised:
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="gate",
            agent="gate_reviser",
            type="revised_plan",
            content=revised,
        ))

        result = dict(previous) if previous else {}
        result["plan"] = revised
        result["success"] = True
        result["gate_feedback"] = user_input
        Display.phase("gate", "Plan revised - continuing pipeline")
        return result

    # Revision failed - pass through with feedback appended
    Display.step_error("gate", "Revision failed, continuing with original + feedback")
    result = dict(previous) if previous else {}
    result["success"] = True
    result["gate_feedback"] = user_input
    return result
