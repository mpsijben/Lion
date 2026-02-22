"""pair() - Real-time pair programming with stream interruption.

One lead agent generates code while "eye" agents monitor the stream
and can interrupt when they spot issues. Closed-loop control for LLM generation.

Usage in pipeline:
    "Build auth" -> pair(claude, eyes: sec+arch)
    "Build API" -> pair(claude.opus, eyes: sec.gemini+arch.haiku)
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from ..interceptors import get_interceptor, StreamInterceptor
from ..lenses import get_lens, Lens
from ..lenses.auto_assign import auto_assign_lenses
from ..memory import MemoryEntry
from ..display import Display
from .impl import _get_git_status_snapshot, _extract_files_changed


@dataclass
class Finding:
    lens: str
    description: str
    eye_name: str
    latency: float


@dataclass
class EyeConfig:
    lens_name: str
    lens: Lens
    provider: str
    interceptor: StreamInterceptor

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.lens_name}"


def _parse_eyes(eyes_str: str, default_provider: str, cwd: str) -> list[EyeConfig]:
    """Parse eyes specification into EyeConfig list.

    Formats:
        "sec+arch"                    -> use default provider for all eyes
        "sec.gemini+arch.haiku"       -> per-eye provider override
        "sec+arch.gemini+perf"        -> mixed: some default, some override
    """
    eyes = []
    for part in eyes_str.split("+"):
        part = part.strip()
        if not part:
            continue

        if "." in part:
            lens_name, provider = part.split(".", 1)
        else:
            lens_name = part
            provider = default_provider

        lens = get_lens(lens_name)
        if lens is None:
            raise ValueError(
                f"Unknown lens '{lens_name}' in eyes specification. "
                f"Use: sec, arch, perf, quick, maint, dx, data, cost, test_lens"
            )

        interceptor = get_interceptor(provider, cwd=cwd)
        eyes.append(EyeConfig(
            lens_name=lens_name,
            lens=lens,
            provider=provider,
            interceptor=interceptor,
        ))

    return eyes


EYE_CHECK_PROMPT = """You are a code reviewer with a specific focus.

{lens_inject}

Review the code below. If there are NO issues in your focus area, reply with
exactly the word NONE. If there are issues, describe the most critical one in
ONE sentence -- be specific about what and where.

Code so far:
```
{code}
```"""


def _build_eye_prompt(lens: Lens, code: str) -> str:
    return EYE_CHECK_PROMPT.format(
        lens_inject=lens.prompt_inject,
        code=code[-8000:],  # last 8000 chars to stay within context limits
    )


def _check_eye(eye: EyeConfig, code: str) -> Finding | None:
    """Run a single eye check. Returns Finding or None if clean."""
    prompt = _build_eye_prompt(eye.lens, code)
    start = time.time()

    eye.interceptor.start(prompt, resume=False)
    response = ""
    for chunk in eye.interceptor.chunks():
        response += chunk.text

    latency = time.time() - start

    if "NONE" in response.upper():
        return None

    return Finding(
        lens=eye.lens_name,
        description=response.strip()[:500],
        eye_name=eye.name,
        latency=latency,
    )


def _check_eyes_parallel(eyes: list[EyeConfig], code: str) -> list[Finding]:
    """Run all eyes in parallel. Return list of findings (empty if all clean)."""
    if not eyes:
        return []

    findings = []
    with ThreadPoolExecutor(max_workers=len(eyes)) as pool:
        futures = {pool.submit(_check_eye, eye, code): eye for eye in eyes}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    findings.append(result)
            except Exception:
                pass  # eye failure should not crash the pair loop

    return findings


def _build_correction_prompt(findings: list[Finding]) -> str:
    lines = ["Code reviewers found the following issues:\n"]
    for f in findings:
        lines.append(f"[{f.lens.upper()}]: {f.description}")
    lines.append(
        "\nFix these issues in the code you've written and continue "
        "implementing. Do not restart from scratch."
    )
    return "\n".join(lines)


LEAD_PROMPT = """Implement the following task. Write complete, working code.

TASK: {prompt}
{plan_section}
Write all necessary code changes. Be thorough and implement everything needed."""

LEAD_PROMPT_PLAN_SECTION = """
PLAN (from previous deliberation):
{plan}

DELIBERATION CONTEXT:
{deliberation}

Follow the plan above closely. Make all code changes needed."""


def _build_lead_prompt(prompt: str, previous: dict) -> str:
    plan = previous.get("plan", "")
    deliberation = previous.get("deliberation_summary", "")

    if plan:
        plan_section = LEAD_PROMPT_PLAN_SECTION.format(
            plan=plan[:20000],
            deliberation=deliberation[:5000] if deliberation else "(none)",
        )
    else:
        plan_section = ""

    return LEAD_PROMPT.format(prompt=prompt, plan_section=plan_section)


def execute_pair(prompt, previous, step, memory, config, cwd, cost_manager=None):
    """Execute pair() - real-time pair programming with stream interruption.

    Args:
        step.args[0]: Lead model name (e.g. "claude", "claude.opus"). Optional.
        step.kwargs["eyes"]: Eye specification (e.g. "sec+arch", "sec.gemini+arch.haiku"). Optional.
    """
    pair_config = config.get("pair", {})
    check_interval = pair_config.get("check_every_n_lines", 20)
    max_interrupts = pair_config.get("max_interrupts", 10)
    default_provider = config.get("providers", {}).get("default", "claude")

    # Parse lead model
    lead_model = step.args[0] if step.args else default_provider
    lead_provider = lead_model.split(".", 1)[0]

    # Parse eyes
    eyes_str = step.kwargs.get("eyes", "")
    if eyes_str:
        eyes = _parse_eyes(eyes_str, default_provider=default_provider, cwd=cwd)
    else:
        # Auto-assign lenses based on task
        lens_names = auto_assign_lenses(prompt, 2)
        eyes = _parse_eyes(
            "+".join(lens_names),
            default_provider=default_provider,
            cwd=cwd,
        )

    # Display - show provider-qualified names when eye uses non-default provider
    eye_labels = []
    for e in eyes:
        if e.provider != default_provider:
            eye_labels.append(f"{e.lens_name}.{e.provider}")
        else:
            eye_labels.append(e.lens_name)
    Display.pair_start(lead_model, eye_labels)

    # Build lead prompt
    lead_prompt = _build_lead_prompt(prompt, previous or {})

    # Create lead interceptor
    lead = get_interceptor(lead_model, cwd=cwd)

    # Log start to memory
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="pair",
        agent="pair_orchestrator",
        type="pair_start",
        content=f"pair({lead_model}, eyes: {'+'.join(eye_labels)})",
        metadata={
            "lead_model": lead_model,
            "eyes": [e.name for e in eyes],
            "check_interval": check_interval,
            "max_interrupts": max_interrupts,
        },
    ))

    # Git status before
    before_snapshot = _get_git_status_snapshot(cwd)

    # The pair loop
    lead_output = ""
    all_findings: list[Finding] = []
    interrupt_count = 0
    lines_since_check = 0
    start_time = time.time()

    Display.phase("pair", f"Lead ({lead_provider}) building, {len(eyes)} eye(s) watching...")

    lead.start(lead_prompt)
    complete = False

    while not complete and interrupt_count < max_interrupts:
        for chunk in lead.chunks():
            lead_output += chunk.text
            lines_since_check += chunk.text.count("\n")

            # Time to check?
            if lines_since_check >= check_interval:
                lines_since_check = 0

                findings = _check_eyes_parallel(eyes, lead_output)

                if findings:
                    # INTERRUPT
                    lead.terminate()
                    interrupt_count += 1
                    all_findings.extend(findings)

                    for f in findings:
                        Display.pair_finding(f.eye_name, f.lens, f.description, f.latency)
                        memory.write(MemoryEntry(
                            timestamp=time.time(),
                            phase="pair",
                            agent=f.eye_name,
                            type="finding",
                            content=f.description,
                            metadata={"lens": f.lens, "latency": f.latency},
                        ))

                    Display.pair_interrupt(interrupt_count, len(findings))

                    correction = _build_correction_prompt(findings)
                    memory.write(MemoryEntry(
                        timestamp=time.time(),
                        phase="pair",
                        agent="pair_orchestrator",
                        type="interrupt",
                        content=correction,
                        metadata={"interrupt_number": interrupt_count},
                    ))

                    lead.resume(correction)
                    break  # restart chunks() from resumed process
                else:
                    Display.pair_clean(len(eyes))
        else:
            # Lead finished without interrupt
            complete = True

    wall_clock = time.time() - start_time
    total_lines = lead_output.count("\n")

    Display.pair_complete(interrupt_count, wall_clock, total_lines)

    # Git status after
    after_snapshot = _get_git_status_snapshot(cwd)
    files_changed = _extract_files_changed(before_snapshot, after_snapshot)

    # Log completion
    memory.write(MemoryEntry(
        timestamp=time.time(),
        phase="pair",
        agent="pair_orchestrator",
        type="pair_complete",
        content=f"Completed: {interrupt_count} interrupts, {total_lines} lines, {wall_clock:.1f}s",
        metadata={
            "interrupts": interrupt_count,
            "lines": total_lines,
            "wall_clock": wall_clock,
            "findings_count": len(all_findings),
            "files_changed": files_changed,
        },
    ))

    return {
        "success": True,
        "code": lead_output,
        "content": lead_output,
        "files_changed": files_changed,
        "tokens_used": 0,  # CLI calls on Max subscription don't track tokens
        "interrupts": interrupt_count,
        "findings": [
            {"lens": f.lens, "description": f.description,
             "eye": f.eye_name, "latency": f.latency}
            for f in all_findings
        ],
        "wall_clock": wall_clock,
    }
