"""Execute a parsed pipeline of steps."""

import time
from dataclasses import dataclass

from .parser import PipelineStep
from .memory import SharedMemory, MemoryEntry
from .display import Display
from .providers import get_provider
from .functions import FUNCTIONS

# Functions that produce code (call implement(), write files to disk)
PRODUCER_FUNCTIONS = {"pride", "test"}

FEEDBACK_PROMPT = """{prompt}

PREVIOUS DELIBERATION:
{deliberation}

FEEDBACK FROM {step_name}:
{feedback}

Apply the feedback above to improve the existing implementation. Focus on addressing
the issues and critiques raised. Make targeted changes - do not rewrite everything."""


@dataclass
class PipelineResult:
    success: bool
    prompt: str
    steps_completed: int
    total_steps: int
    outputs: list[dict]
    total_duration: float
    total_tokens: int
    files_changed: list[str]
    errors: list[str]
    agent_summaries: list[dict] = None
    final_decision: str = None
    content: str = None

    def __post_init__(self):
        if self.agent_summaries is None:
            self.agent_summaries = []


def _needs_refinement(step_result):
    """Determine if a step's output warrants a feedback re-run.

    Returns True if the step produced actionable feedback (issues, errors, critiques).
    """
    if step_result.get("critical_count", 0) > 0:
        return True
    if step_result.get("warning_count", 0) > 0:
        return True
    if step_result.get("issues") and len(step_result["issues"]) > 0:
        return True
    if step_result.get("has_feedback", False):
        return True
    if step_result.get("errors_count", 0) > 0:
        return True
    return False


class PipelineExecutor:
    def __init__(self, prompt, steps, config, run_dir, cwd, cost_manager=None):
        self.prompt = prompt
        self.steps = self._expand_patterns(steps)
        self.config = config
        self.run_dir = run_dir
        self.cwd = cwd
        self.cost_manager = cost_manager
        self.memory = SharedMemory(run_dir)
        self.outputs = []
        self.files_changed = []
        self.errors = []
        self.total_tokens = 0
        self.agent_summaries = []
        self.final_decision = None

    def _expand_patterns(self, steps):
        """Expand __pattern__ meta-steps into actual steps."""
        expanded = []
        for step in steps:
            if step.function == "__pattern__":
                expanded.extend(step.args)
            else:
                expanded.append(step)
        return expanded

    def run(self) -> PipelineResult:
        """Execute the full pipeline."""
        start_time = time.time()

        Display.pipeline_start(self.prompt, self.steps)

        # If no pipeline steps, just run a single agent
        if not self.steps:
            result = self._run_single_agent()
            content = result.get("content", "")
            return PipelineResult(
                success=result.get("success", False),
                prompt=self.prompt,
                steps_completed=1,
                total_steps=1,
                outputs=[result],
                total_duration=time.time() - start_time,
                total_tokens=self.total_tokens,
                files_changed=result.get("files_changed", []),
                errors=[],
                content=content,
            )

        # Execute pipeline steps sequentially
        previous_output = {"prompt": self.prompt, "code": "", "decisions": []}

        for i, step in enumerate(self.steps):
            Display.step_start(i + 1, len(self.steps), step)

            func = FUNCTIONS.get(step.function)
            if not func:
                self.errors.append(f"Unknown function: {step.function}")
                Display.step_error(step.function, "Unknown function")
                continue

            try:
                step_result = func(
                    prompt=self.prompt,
                    previous=previous_output,
                    step=step,
                    memory=self.memory,
                    config=self.config,
                    cwd=self.cwd,
                    cost_manager=self.cost_manager,
                )

                self.outputs.append(step_result)
                self.total_tokens += step_result.get("tokens_used", 0)
                self.files_changed.extend(step_result.get("files_changed", []))

                # Collect summaries from pride steps
                if step_result.get("agent_summaries"):
                    self.agent_summaries = step_result["agent_summaries"]
                if step_result.get("final_decision"):
                    self.final_decision = step_result["final_decision"]

                previous_output = {**previous_output, **step_result}

                # Handle feedback loop: <-> or <N-> operator
                if step.feedback and _needs_refinement(step_result):
                    producer_step, producer_idx = self._find_last_producer(i)
                    if producer_step:
                        Display.phase(
                            "refine",
                            f"Re-running {producer_step.function} with "
                            f"{step.function} feedback...",
                        )
                        refine_result = self._run_feedback_loop(
                            feedback_step=step,
                            feedback_result=step_result,
                            producer_step=producer_step,
                            previous=previous_output,
                        )
                        if refine_result:
                            self.outputs.append(refine_result)
                            self.total_tokens += refine_result.get("tokens_used", 0)
                            self.files_changed.extend(
                                refine_result.get("files_changed", [])
                            )
                            if refine_result.get("agent_summaries"):
                                self.agent_summaries = refine_result["agent_summaries"]
                            if refine_result.get("final_decision"):
                                self.final_decision = refine_result["final_decision"]
                            previous_output = {**previous_output, **refine_result}

                Display.step_complete(step.function, step_result)

            except Exception as e:
                self.errors.append(f"{step.function}: {str(e)}")
                Display.step_error(step.function, str(e))
                break

        return PipelineResult(
            success=len(self.errors) == 0,
            prompt=self.prompt,
            steps_completed=len(self.outputs),
            total_steps=len(self.steps),
            outputs=self.outputs,
            total_duration=time.time() - start_time,
            total_tokens=self.total_tokens,
            files_changed=list(set(self.files_changed)),
            errors=self.errors,
            agent_summaries=self.agent_summaries,
            final_decision=self.final_decision,
        )

    def _find_last_producer(self, current_idx):
        """Find the last producer step before current_idx.

        A producer is a step that generates/modifies code (e.g. pride, test).
        Returns (step, index) or (None, -1) if no producer found.
        """
        for idx in range(current_idx - 1, -1, -1):
            if self.steps[idx].function in PRODUCER_FUNCTIONS:
                return self.steps[idx], idx
        return None, -1

    def _run_feedback_loop(self, feedback_step, feedback_result, producer_step,
                           previous):
        """Re-run the producer step with feedback from the current step.

        Uses the feedback_agents override if specified, otherwise uses the
        original agent count from the producer step.
        """
        # Determine agent count for the re-run
        if feedback_step.feedback_agents is not None:
            agent_count = feedback_step.feedback_agents
        elif producer_step.args and isinstance(producer_step.args[0], int):
            agent_count = producer_step.args[0]
        else:
            agent_count = 1  # Safe default

        # Build feedback text
        feedback_text = feedback_result.get("content", "")
        if not feedback_text:
            issues = feedback_result.get("issues", [])
            if issues:
                feedback_text = "\n".join(
                    f"- [{i.get('severity', 'issue')}] "
                    f"{i.get('title', i.get('message', str(i)))}"
                    for i in issues
                )

        if not feedback_text:
            Display.notify(
                f"No actionable feedback from {feedback_step.function}, "
                f"skipping re-run"
            )
            return None

        # Build the augmented prompt with feedback context
        deliberation = previous.get("deliberation_summary", "")
        augmented_prompt = FEEDBACK_PROMPT.format(
            prompt=self.prompt,
            deliberation=deliberation[:40000] if deliberation else "(none)",
            step_name=feedback_step.function,
            feedback=feedback_text[:20000],
        )

        # Create a new PipelineStep for the re-run with the right agent count
        rerun_step = PipelineStep(
            function=producer_step.function,
            args=[agent_count] + producer_step.args[1:],
            kwargs=producer_step.kwargs,
        )

        # Re-run the producer function
        func = FUNCTIONS.get(producer_step.function)
        if not func:
            return None

        Display.notify(
            f"Re-running {producer_step.function}({agent_count}) "
            f"with {feedback_step.function} feedback"
        )

        try:
            result = func(
                prompt=augmented_prompt,
                previous=previous,
                step=rerun_step,
                memory=self.memory,
                config=self.config,
                cwd=self.cwd,
                cost_manager=self.cost_manager,
            )

            # Log the feedback loop to memory
            self.memory.write(MemoryEntry(
                timestamp=time.time(),
                phase="refine",
                agent="feedback_loop",
                type="rerun",
                content=f"Re-ran {producer_step.function}({agent_count}) "
                        f"based on {feedback_step.function} feedback",
                metadata={
                    "producer": producer_step.function,
                    "feedback_from": feedback_step.function,
                    "agent_count": agent_count,
                },
            ))

            return result

        except Exception as e:
            Display.step_error(
                "refine",
                f"Feedback re-run failed: {str(e)}"
            )
            return None

    def _run_single_agent(self) -> dict:
        """Run a single agent without pipeline (for simple tasks)."""
        provider = get_provider(
            self.config.get("providers", {}).get("default", "claude"),
            self.config,
        )
        result = provider.implement(self.prompt, cwd=self.cwd)
        return {
            "success": result.success,
            "content": result.content,
            "tokens_used": result.tokens_used,
            "files_changed": [],
        }
