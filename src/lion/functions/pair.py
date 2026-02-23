"""pair() - Real-time pair programming with stream interruption.

One lead agent generates code while "eye" agents monitor the stream
and can interrupt when they spot issues. Closed-loop control for LLM generation.

Usage in pipeline:
    "Build auth" -> pair(claude, eyes: sec+arch)
    "Build API" -> pair(claude.opus, eyes: sec.gemini+arch.haiku)
"""

import queue
import threading
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

    def fresh_interceptor(self) -> StreamInterceptor:
        """Create a fresh interceptor instance for a new check cycle."""
        try:
            return get_interceptor(self.provider, cwd=self.interceptor.cwd)
        except (ValueError, RuntimeError):
            # Fallback for mock/test interceptors not in registry
            return self.interceptor


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

Review the code below. Only report issues that MATTER -- things that would
cause bugs, security holes, data loss, or block reasonable future changes.
Do NOT report style preferences, theoretical improvements, or "nice to have"
refactors. If the code works correctly and is reasonably structured, reply
with exactly the word NONE.

If there ARE real issues, list them -- one per line, each starting with a
dash (-). Be specific about what and where (file, function, line if possible).
Keep each issue to one sentence.
{previous_findings_section}
Code so far:
```
{code}
```"""

EYE_PREVIOUS_FINDINGS_SECTION = """
The following issues were ALREADY found and the developer is fixing them.
Do NOT report these again -- only report NEW issues not covered below:

{previous_findings}
"""


PREFLIGHT_PROMPT = """You are a code reviewer catching issues BEFORE code is written.

{lens_inject}

A developer is about to implement the following task:

TASK: {task}
{thinking_section}
Based on the task and the developer's thinking, predict ALL likely issues
in your focus area that the implementation will have. List each issue on its
own line starting with a dash (-). Be specific about what to watch out for.

If the task seems safe in your focus area, reply with exactly the word NONE."""

PREFLIGHT_THINKING_SECTION = """
The developer is currently thinking through the implementation. Here is their
reasoning so far:

DEVELOPER THINKING:
{thinking}
"""


def _build_eye_prompt(
    lens: Lens, code: str, previous_findings: list["Finding"] | None = None,
) -> str:
    if previous_findings:
        pf_text = "\n".join(
            f"- [{f.lens.upper()}] {f.description}" for f in previous_findings
        )
        previous_section = EYE_PREVIOUS_FINDINGS_SECTION.format(
            previous_findings=pf_text[-3000:],
        )
    else:
        previous_section = ""
    return EYE_CHECK_PROMPT.format(
        lens_inject=lens.prompt_inject,
        code=code[-8000:],  # last 8000 chars to stay within context limits
        previous_findings_section=previous_section,
    )


def _build_preflight_prompt(lens: Lens, task: str, thinking: str = "") -> str:
    if thinking:
        thinking_section = PREFLIGHT_THINKING_SECTION.format(
            thinking=thinking[-6000:],  # last 6000 chars of thinking
        )
    else:
        thinking_section = ""
    return PREFLIGHT_PROMPT.format(
        lens_inject=lens.prompt_inject,
        task=task[:4000],
        thinking_section=thinking_section,
    )


@dataclass
class EyeUsage:
    """Token usage from a single eye check."""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class EyeResult:
    """Result of a single eye check -- finding, clean, empty, or error."""
    eye_name: str
    finding: Finding | None
    status: str  # "finding", "clean", "empty", "error"
    latency: float
    error: str | None = None
    usage: EyeUsage | None = None


def _check_eye(
    eye: EyeConfig, code: str, prompt_override: str = None,
    previous_findings: list["Finding"] | None = None,
) -> EyeResult:
    """Run a single eye check. Returns EyeResult with status.

    Creates a fresh interceptor per check so slow eyes from a previous cycle
    don't block new checks (each eye runs its own subprocess).
    """
    prompt = prompt_override or _build_eye_prompt(
        eye.lens, code, previous_findings=previous_findings,
    )
    start = time.time()

    interceptor = None
    try:
        interceptor = eye.fresh_interceptor()
        interceptor.start(prompt, resume=False)
        response = ""
        for chunk in interceptor.chunks():
            # Skip tool_use chunks (shell commands, file writes) - only
            # collect text/code output which contains the actual review
            if getattr(chunk, "kind", "code") == "tool_use":
                continue
            response += chunk.text
    except Exception as e:
        return EyeResult(
            eye_name=eye.name, finding=None,
            status="error", latency=time.time() - start,
            error=str(e),
        )

    latency = time.time() - start
    cleaned = response.strip()

    # Capture usage from the interceptor
    eye_usage = None
    if interceptor:
        eye_usage = EyeUsage(
            input_tokens=interceptor.stats.input_tokens,
            output_tokens=interceptor.stats.output_tokens,
            cost_usd=interceptor.stats.cost_usd,
        )

    if not cleaned:
        return EyeResult(
            eye_name=eye.name, finding=None,
            status="empty", latency=latency, usage=eye_usage,
        )

    if "NONE" in response.upper():
        return EyeResult(
            eye_name=eye.name, finding=None,
            status="clean", latency=latency, usage=eye_usage,
        )

    finding = Finding(
        lens=eye.lens_name,
        description=cleaned[:2000],
        eye_name=eye.name,
        latency=latency,
    )
    return EyeResult(
        eye_name=eye.name, finding=finding,
        status="finding", latency=latency, usage=eye_usage,
    )


def _check_eyes_parallel(
    eyes: list[EyeConfig], code: str,
    usage_sink: list | None = None,
    previous_findings: list["Finding"] | None = None,
) -> list[Finding]:
    """Run all eyes in parallel. Return list of findings (empty if all clean).

    If usage_sink is provided, appends per-eye usage dicts to it.
    If previous_findings is provided, eyes are told not to re-report them.
    """
    if not eyes:
        return []

    findings = []
    with ThreadPoolExecutor(max_workers=len(eyes)) as pool:
        futures = {
            pool.submit(
                _check_eye, eye, code,
                previous_findings=previous_findings,
            ): eye
            for eye in eyes
        }
        for future in as_completed(futures):
            result = future.result()
            if result.usage and usage_sink is not None:
                usage_sink.append({
                    "agent": result.eye_name,
                    "role": "eye",
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "cost_usd": result.usage.cost_usd,
                })
            if result.status == "finding" and result.finding:
                findings.append(result.finding)
            elif result.status == "error":
                Display.pair_eye_error(result.eye_name, result.error)
            elif result.status == "empty":
                Display.pair_eye_error(result.eye_name, "empty response")

    return findings


class _EyeChecker:
    """Runs eye checks on a background thread. Eyes operate independently.

    Each eye runs as a separate thread. When an eye finishes with a finding,
    it's immediately available via poll(). The main loop interrupts the lead
    on the first finding. Meanwhile, slower eyes keep running -- when they
    finish later, they can trigger another interrupt.

    New checks can be submitted while previous eyes are still running.
    The checker tracks how many eyes are still in-flight via pending_count.
    """

    def __init__(self, eyes: list[EyeConfig], usage_sink: list | None = None):
        self._eyes = eyes
        self._findings: queue.Queue[Finding] = queue.Queue()
        self._usage_sink = usage_sink
        self._pending_count = 0
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        """True if any eye from any check cycle is still running."""
        with self._lock:
            return self._pending_count > 0

    def submit(self, code: str, previous_findings: list["Finding"] | None = None) -> None:
        """Start all eyes in background. Non-blocking. Can be called while
        previous eyes are still running -- they keep going independently."""
        if not self._eyes:
            return
        with self._lock:
            self._pending_count += len(self._eyes)
        for eye in self._eyes:
            t = threading.Thread(
                target=self._run_eye,
                args=(eye, code, previous_findings),
                daemon=True,
            )
            t.start()

    def _run_eye(self, eye: EyeConfig, code: str,
                 previous_findings: list["Finding"] | None) -> None:
        try:
            result = _check_eye(eye, code, previous_findings=previous_findings)
            if result.usage and self._usage_sink is not None:
                self._usage_sink.append({
                    "agent": result.eye_name,
                    "role": "eye",
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "cost_usd": result.usage.cost_usd,
                })
            if result.status == "finding" and result.finding:
                self._findings.put(result.finding)
            elif result.status == "error":
                Display.pair_eye_error(result.eye_name, result.error)
            elif result.status == "empty":
                Display.pair_eye_error(result.eye_name, "empty response")
        finally:
            with self._lock:
                self._pending_count -= 1

    def poll(self) -> Finding | None:
        """Non-blocking poll. Returns a Finding or None."""
        try:
            return self._findings.get_nowait()
        except queue.Empty:
            return None

    def drain(self) -> list[Finding]:
        """Wait for all in-flight eyes and return all findings."""
        # Spin until no eyes are pending
        while self.busy:
            time.sleep(0.1)
        findings = []
        while True:
            item = self.poll()
            if item is None:
                break
            findings.append(item)
        return findings


class _PreflightChecker:
    """Runs preflight eye checks during lead's thinking phase.

    Uses the task prompt + lead's thinking context to predict issues before
    code is written. Creates its own interceptors so it doesn't conflict
    with code-review eyes.
    """

    def __init__(self, eyes: list[EyeConfig], task: str, cwd: str,
                 thinking: str = ""):
        self._task = task
        self._thinking = thinking
        self._findings: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._done = False

        # Create separate interceptors for preflight (can't share with code eyes)
        self._preflight_eyes = []
        for eye in eyes:
            preflight_interceptor = get_interceptor(eye.provider, cwd=cwd)
            self._preflight_eyes.append(EyeConfig(
                lens_name=eye.lens_name,
                lens=eye.lens,
                provider=eye.provider,
                interceptor=preflight_interceptor,
            ))

    def start(self) -> None:
        """Start preflight checks in background. Call right after lead.start()."""
        self._thread = threading.Thread(
            target=self._run, daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            if not self._preflight_eyes:
                return
            with ThreadPoolExecutor(max_workers=len(self._preflight_eyes)) as pool:
                futures = {}
                for eye in self._preflight_eyes:
                    prompt = _build_preflight_prompt(
                        eye.lens, self._task, self._thinking,
                    )
                    futures[pool.submit(
                        _check_eye, eye, "", prompt_override=prompt
                    )] = eye
                for future in as_completed(futures):
                    result = future.result()
                    if result.status == "finding" and result.finding:
                        self._findings.put(result.finding)
                    elif result.status == "error":
                        Display.pair_eye_error(
                            f"preflight:{result.eye_name}", result.error
                        )
        finally:
            self._done = True

    def collect(self) -> list[Finding]:
        """Wait for preflight to finish and return findings."""
        if self._thread:
            self._thread.join(timeout=60)
        findings = []
        while not self._findings.empty():
            try:
                findings.append(self._findings.get_nowait())
            except queue.Empty:
                break
        return findings

    @property
    def done(self) -> bool:
        return self._done


def _build_correction_prompt(findings: list[Finding]) -> str:
    lines = ["Code reviewers found the following issues:\n"]
    for f in findings:
        lines.append(f"[{f.lens.upper()}]: {f.description}")
    lines.append(
        "\nFix these issues in the code you've written and continue "
        "implementing. Do not restart from scratch."
    )
    return "\n".join(lines)


def _build_preflight_correction(findings: list[Finding]) -> str:
    lines = ["BEFORE you write code, reviewers flagged these concerns:\n"]
    for f in findings:
        lines.append(f"[{f.lens.upper()}]: {f.description}")
    lines.append(
        "\nAddress these concerns in your implementation. "
        "Make sure the code you write avoids these issues from the start."
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
    first_check_lines = pair_config.get("first_check_lines", 5)
    check_interval = pair_config.get("check_every_n_lines", 10)
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
            "first_check_lines": first_check_lines,
            "check_interval": check_interval,
            "max_interrupts": max_interrupts,
        },
    ))

    # Git status before
    before_snapshot = _get_git_status_snapshot(cwd)

    # The pair loop
    lead_output = ""
    thinking_output = ""
    all_findings: list[Finding] = []
    eye_usage_list: list[dict] = []  # collects per-eye usage from all checks
    interrupt_count = 0
    total_lines = 0
    lines_since_check = 0
    checks_submitted = 0
    start_time = time.time()

    # Preflight config
    preflight_thinking_lines = pair_config.get("preflight_thinking_lines", 50)

    Display.phase("pair", f"Lead ({lead_provider}) building, {len(eyes)} eye(s) watching...")

    lead.start(lead_prompt)
    complete = False

    # Preflight starts when we have enough thinking context
    preflight: _PreflightChecker | None = None
    preflight_collected = False
    thinking_lines = 0

    eye_checker = _EyeChecker(eyes, usage_sink=eye_usage_list)

    def _do_interrupt(findings_list):
        """Handle an interrupt: log new findings, resume lead with new findings only."""
        nonlocal interrupt_count
        interrupt_count += 1
        all_findings.extend(findings_list)

        for f in findings_list:
            Display.pair_finding(f.eye_name, f.lens, f.description, f.latency)
            memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="pair",
                agent=f.eye_name,
                type="finding",
                content=f.description,
                metadata={"lens": f.lens, "latency": f.latency},
            ))

        Display.pair_interrupt(interrupt_count, len(findings_list))

        # Lead gets only the NEW findings (it already knows about previous ones
        # from earlier interrupts). Eyes get all_findings via previous_findings
        # so they don't report the same issues again.
        correction = _build_correction_prompt(findings_list)
        memory.write(MemoryEntry(
            timestamp=time.time(),
            phase="pair",
            agent="pair_orchestrator",
            type="interrupt",
            content=correction,
            metadata={"interrupt_number": interrupt_count},
        ))
        return correction

    while not complete and interrupt_count < max_interrupts:
        for chunk in lead.chunks():
            chunk_kind = getattr(chunk, "kind", "code")

            # Thinking chunks: accumulate for preflight context
            if chunk_kind == "thinking":
                thinking_output += chunk.text
                thinking_lines += chunk.text.count("\n") or 1  # count at least 1 per chunk

                # Start preflight when enough thinking context is available
                # Trigger on lines OR chars (Codex sends short reasoning blocks)
                if (
                    preflight is None
                    and (thinking_lines >= preflight_thinking_lines
                         or len(thinking_output) >= preflight_thinking_lines * 80)
                ):
                    preflight = _PreflightChecker(
                        eyes, prompt, cwd, thinking=thinking_output,
                    )
                    preflight.start()
                    Display.pair_preflight_started(
                        len(eyes), thinking_lines,
                    )
                continue  # thinking chunks don't count toward code lines

            # Code and tool_use chunks -- accumulate output
            lead_output += chunk.text
            new_lines = chunk.text.count("\n")
            total_lines += new_lines
            lines_since_check += new_lines
            Display.pair_lead_chunk(lead_model, chunk.text)

            # Collect preflight findings on first code output
            if not preflight_collected and total_lines > 0 and preflight is not None:
                preflight_collected = True
                pf_findings = preflight.collect()
                if pf_findings:
                    lead.terminate()
                    all_findings.extend(pf_findings)
                    for f in pf_findings:
                        Display.pair_preflight_finding(
                            f.eye_name, f.lens, f.description, f.latency
                        )
                        memory.write(MemoryEntry(
                            timestamp=time.time(),
                            phase="pair",
                            agent=f"preflight:{f.eye_name}",
                            type="preflight_finding",
                            content=f.description,
                            metadata={"lens": f.lens, "latency": f.latency},
                        ))

                    correction = _build_preflight_correction(pf_findings)
                    Display.pair_interrupt(
                        interrupt_count + 1, len(pf_findings),
                        preflight=True,
                    )
                    interrupt_count += 1
                    memory.write(MemoryEntry(
                        timestamp=time.time(),
                        phase="pair",
                        agent="pair_orchestrator",
                        type="preflight_interrupt",
                        content=correction,
                        metadata={"interrupt_number": interrupt_count},
                    ))
                    lead.resume(correction)
                    # Fresh eye checker for resumed code
                    eye_checker = _EyeChecker(eyes, usage_sink=eye_usage_list)
                    lines_since_check = 0
                    break  # restart chunks() from resumed process
                else:
                    Display.pair_preflight_clean()

            # Use shorter interval for first check (early start for eyes)
            threshold = first_check_lines if checks_submitted == 0 else check_interval

            # Submit eye check if interval reached and no check running
            if lines_since_check >= threshold and not eye_checker.busy:
                lines_since_check = 0
                checks_submitted += 1
                elapsed = time.time() - start_time
                Display.pair_check_submitted(
                    checks_submitted, total_lines, elapsed
                )
                eye_checker.submit(lead_output, previous_findings=all_findings)

            # Poll for any finding (non-blocking).
            # Interrupt on the first finding. Slower eyes keep running
            # and can trigger another interrupt when they finish later.
            item = eye_checker.poll()
            if isinstance(item, Finding):
                lead.terminate()
                # Grab any other findings already in the queue
                cycle_findings = [item]
                while True:
                    more = eye_checker.poll()
                    if more is None:
                        break
                    cycle_findings.append(more)

                correction = _do_interrupt(cycle_findings)
                lead.resume(correction)
                # Don't reset eye_checker -- slower eyes keep running
                # and will trigger another interrupt when they finish
                lines_since_check = 0
                break  # restart chunks() from resumed process
        else:
            # Lead finished without interrupt
            complete = True

    # Report thinking stats for debugging preflight trigger
    if thinking_lines > 0:
        Display.phase(
            "pair",
            f"Thinking: {thinking_lines} lines"
            f" (preflight {'triggered' if preflight is not None else f'needs {preflight_thinking_lines}'})",
        )

    # Final eye check loop: review COMPLETE output, re-check until clean.
    # Any in-flight background check only covered a partial snapshot, so we
    # run fresh synchronous checks over the full output until eyes are happy.
    max_final_rounds = pair_config.get("max_final_rounds", 3)
    final_round = 0
    if lead_output.strip() and complete:
        # Discard any in-flight background check (it reviewed old code)
        if eye_checker.busy:
            Display.phase("pair", "Lead done, discarding partial eye check...")

        while final_round < max_final_rounds:
            final_round += 1
            Display.phase(
                "pair",
                f"Final eye check round {final_round}/{max_final_rounds} "
                f"on complete output...",
            )
            final_findings = _check_eyes_parallel(
                eyes, lead_output,
                usage_sink=eye_usage_list,
                previous_findings=all_findings,
            )
            if final_findings:
                correction = _do_interrupt(final_findings)
                lead.resume(correction)
                for chunk in lead.chunks():
                    lead_output += chunk.text
                    Display.pair_lead_chunk(lead_model, chunk.text)
            else:
                Display.pair_clean(len(eyes))
                break
        else:
            Display.phase(
                "pair",
                f"Max final rounds ({max_final_rounds}) reached, "
                f"stopping checks.",
            )

    wall_clock = time.time() - start_time
    total_lines = lead_output.count("\n")  # recount for accuracy after resume

    # Collect usage stats
    lead_usage = {
        "agent": lead_model,
        "role": "lead",
        "input_tokens": lead.stats.input_tokens,
        "output_tokens": lead.stats.output_tokens,
        "cost_usd": lead.stats.cost_usd,
    }

    # Aggregate eye usage
    eye_tokens = sum(e.get("input_tokens", 0) + e.get("output_tokens", 0) for e in eye_usage_list)
    eye_cost = sum(e.get("cost_usd", 0.0) for e in eye_usage_list)

    total_tokens = lead.stats.input_tokens + lead.stats.output_tokens + eye_tokens
    total_cost = lead.stats.cost_usd + eye_cost

    Display.pair_complete(interrupt_count, wall_clock, total_lines)
    Display.pair_usage(lead_usage, eye_usage_list, total_tokens, total_cost)

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
            "usage": {
                "lead": lead_usage,
                "eyes": eye_usage_list,
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost,
            },
        },
    ))

    return {
        "success": True,
        "code": lead_output,
        "content": lead_output,
        "files_changed": files_changed,
        "tokens_used": total_tokens,
        "interrupts": interrupt_count,
        "findings": [
            {"lens": f.lens, "description": f.description,
             "eye": f.eye_name, "latency": f.latency}
            for f in all_findings
        ],
        "wall_clock": wall_clock,
        "usage": {
            "lead": lead_usage,
            "eyes": eye_usage_list,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
        },
    }
