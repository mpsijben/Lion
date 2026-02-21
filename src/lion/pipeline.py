"""Execute a parsed pipeline of steps."""

import concurrent.futures
import os
import time
from dataclasses import dataclass

from .parser import PipelineStep
from .memory import SharedMemory, MemoryEntry
from .display import Display
from .providers import get_provider
from .functions import FUNCTIONS
from .context import (
    ContextBudgetManager,
    ContextArchaeologist,
    detect_relevant_files,
    select_context_mode,
)

# Functions that produce code (call implement(), write files to disk)
PRODUCER_FUNCTIONS = {"pride", "test"}

# Maximum feedback rounds before moving on (producer re-run + re-verify = 1 round)
MAX_FEEDBACK_ROUNDS = 2

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


def _build_dependency_levels(subtasks):
    """Group subtask indices into dependency levels for execution ordering.

    Level 0: tasks with no dependencies
    Level 1: tasks that depend only on level 0 tasks
    etc.

    Returns list of lists of task indices.
    """
    n = len(subtasks)
    assigned = {}  # task_idx -> level
    levels = []

    # Keep assigning until all tasks are placed
    for _ in range(n):
        current_level = []
        for i in range(n):
            if i in assigned:
                continue
            deps = subtasks[i].get("depends_on", [])
            # Convert 1-based to 0-based indices
            dep_indices = [d - 1 for d in deps if 1 <= d <= n]
            # Check if all deps are already assigned
            if all(d in assigned for d in dep_indices):
                current_level.append(i)
        if not current_level:
            # Remaining tasks have circular deps - just add them
            remaining = [i for i in range(n) if i not in assigned]
            if remaining:
                levels.append(remaining)
            break
        for i in current_level:
            assigned[i] = len(levels)
        levels.append(current_level)
        if len(assigned) == n:
            break

    return levels


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
        self.steps_completed = 0  # Count only real pipeline steps, not feedback re-runs

        # Layer 2: Context Ecosystem
        self.context_budget = ContextBudgetManager(config)
        self.context_mode = select_context_mode(self.steps, config)

        # Store pipeline steps in config for pride() to access
        self.config["_pipeline_steps"] = self.steps

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

        # Layer 2: Run archaeology to find relevant previous runs
        self._run_archaeology()

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

        # Validate all function names upfront
        unknown = [s.function for s in self.steps
                   if s.function not in FUNCTIONS and s.function != "__pattern__"]
        if unknown:
            for name in unknown:
                Display.step_error(name, f"Unknown function '{name}'")
            return PipelineResult(
                success=False,
                prompt=self.prompt,
                steps_completed=0,
                total_steps=len(self.steps),
                outputs=[],
                total_duration=time.time() - start_time,
                total_tokens=0,
                files_changed=[],
                errors=[f"Unknown function: {name}" for name in unknown],
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

                # Handle task decomposition: run remaining pipeline for each subtask
                if step_result.get("is_task_decomposition"):
                    subtasks = step_result.get("subtasks", [])
                    remaining_steps = self.steps[i + 1:]

                    if subtasks and remaining_steps:
                        self.steps_completed += 1
                        Display.step_complete(step.function, step_result)

                        self._run_subtasks(
                            subtasks, remaining_steps, previous_output
                        )

                        # Skip remaining steps in the main loop
                        # (they've been run per-subtask)
                        break
                    # If no remaining steps, just continue normally

                # Handle feedback loop: <-> or <N-> operator
                # Re-runs the producer, then re-verifies with the same feedback
                # step, up to MAX_FEEDBACK_ROUNDS times.
                if step.feedback and _needs_refinement(step_result):
                    producer_step, producer_idx = self._find_last_producer(i)
                    if producer_step:
                        feedback_result = step_result
                        for round_num in range(MAX_FEEDBACK_ROUNDS):
                            Display.phase(
                                "refine",
                                f"Round {round_num + 1}/{MAX_FEEDBACK_ROUNDS}: "
                                f"Re-running {producer_step.function} with "
                                f"{step.function} feedback...",
                            )
                            refine_result = self._run_feedback_loop(
                                feedback_step=step,
                                feedback_result=feedback_result,
                                producer_step=producer_step,
                                previous=previous_output,
                            )
                            if not refine_result:
                                break

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

                            # Re-verify: run the feedback step again
                            Display.phase(
                                "refine",
                                f"Round {round_num + 1}/{MAX_FEEDBACK_ROUNDS}: "
                                f"Re-verifying with {step.function}...",
                            )
                            verify_result = func(
                                prompt=self.prompt,
                                previous=previous_output,
                                step=step,
                                memory=self.memory,
                                config=self.config,
                                cwd=self.cwd,
                                cost_manager=self.cost_manager,
                            )
                            self.outputs.append(verify_result)
                            self.total_tokens += verify_result.get("tokens_used", 0)
                            previous_output = {**previous_output, **verify_result}

                            # If no more issues, break out of the loop
                            if not _needs_refinement(verify_result):
                                Display.notify(
                                    f"{step.function} passed after "
                                    f"{round_num + 1} round(s)"
                                )
                                break

                            feedback_result = verify_result

                        else:
                            # Exhausted all rounds without passing
                            Display.notify(
                                f"Max feedback rounds ({MAX_FEEDBACK_ROUNDS}) "
                                f"reached, continuing pipeline"
                            )

                self.steps_completed += 1
                Display.step_complete(step.function, step_result)
                Display.step_summary(step.function, step_result)

            except Exception as e:
                self.errors.append(f"{step.function}: {str(e)}")
                Display.step_error(step.function, str(e))
                break

        return PipelineResult(
            success=len(self.errors) == 0,
            prompt=self.prompt,
            steps_completed=self.steps_completed,
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

    def _find_producer_in_steps(self, steps, current_idx):
        """Find the last producer step before current_idx in a given step list.

        Used by subtask runner where self.steps is the main pipeline,
        not the subtask's remaining steps.
        """
        for idx in range(current_idx - 1, -1, -1):
            if steps[idx].function in PRODUCER_FUNCTIONS:
                return steps[idx]
        return None

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

    def _run_subtasks(self, subtasks, remaining_steps, previous_output):
        """Run remaining pipeline steps for each subtask.

        Groups subtasks by dependency level and runs independent subtasks
        sequentially (parallel support can be added later).
        """

        # Build dependency graph: group tasks by level
        levels = _build_dependency_levels(subtasks)

        for level_idx, level_tasks in enumerate(levels):
            # Clear task label for level-wide messages
            Display.set_task_label(None)
            Display.phase(
                "task",
                f"Level {level_idx + 1}/{len(levels)}: "
                f"{len(level_tasks)} subtask(s)",
            )

            # Check if all tasks in this level are parallel-safe
            all_parallel = all(
                subtasks[t_idx].get("parallel", False)
                for t_idx in level_tasks
            )

            if all_parallel and len(level_tasks) > 1:
                # Run parallel subtasks concurrently
                self._run_subtasks_parallel(
                    [subtasks[i] for i in level_tasks],
                    remaining_steps,
                    previous_output,
                    level_tasks,
                )
            else:
                # Run sequentially
                for task_idx in level_tasks:
                    subtask = subtasks[task_idx]
                    self._run_single_subtask(
                        subtask, task_idx + 1, len(subtasks),
                        remaining_steps, previous_output,
                    )

    def _run_single_subtask(self, subtask, task_num, total_tasks,
                            remaining_steps, previous_output):
        """Run the remaining pipeline steps for one subtask."""
        title = subtask.get("title", f"Subtask {task_num}")
        description = subtask.get("description", "")

        # Set thread-local task label so all Display output is prefixed
        task_label = f"Task {task_num}/{total_tasks}"
        Display.set_task_label(task_label)

        Display.notify(f"--- {title} ---")

        # Build the subtask prompt
        subtask_prompt = (
            f"{self.prompt}\n\n"
            f"FOCUS ON THIS SPECIFIC SUBTASK:\n"
            f"Task {task_num}: {title}\n"
            f"{description}\n"
        )
        if subtask.get("files"):
            subtask_prompt += f"Files: {', '.join(subtask['files'])}\n"

        # Run each remaining step with the subtask prompt
        subtask_previous = {**previous_output}

        for j, step in enumerate(remaining_steps):
            Display.step_start(
                j + 1, len(remaining_steps), step,
            )

            func = FUNCTIONS.get(step.function)
            if not func:
                self.errors.append(f"Unknown function: {step.function}")
                Display.step_error(step.function, "Unknown function")
                continue

            try:
                step_result = func(
                    prompt=subtask_prompt,
                    previous=subtask_previous,
                    step=step,
                    memory=self.memory,
                    config=self.config,
                    cwd=self.cwd,
                    cost_manager=self.cost_manager,
                )

                self.outputs.append(step_result)
                self.total_tokens += step_result.get("tokens_used", 0)
                self.files_changed.extend(
                    step_result.get("files_changed", [])
                )

                if step_result.get("agent_summaries"):
                    self.agent_summaries = step_result["agent_summaries"]
                if step_result.get("final_decision"):
                    self.final_decision = step_result["final_decision"]

                subtask_previous = {**subtask_previous, **step_result}

                # Handle feedback loop: <-> or <N-> operator
                if step.feedback and _needs_refinement(step_result):
                    producer_step = self._find_producer_in_steps(
                        remaining_steps, j
                    )
                    if producer_step:
                        feedback_result = step_result
                        for round_num in range(MAX_FEEDBACK_ROUNDS):
                            Display.phase(
                                "refine",
                                f"Round {round_num + 1}/{MAX_FEEDBACK_ROUNDS}: "
                                f"Re-running {producer_step.function} with "
                                f"{step.function} feedback...",
                            )
                            refine_result = self._run_feedback_loop(
                                feedback_step=step,
                                feedback_result=feedback_result,
                                producer_step=producer_step,
                                previous=subtask_previous,
                            )
                            if not refine_result:
                                break

                            self.outputs.append(refine_result)
                            self.total_tokens += refine_result.get(
                                "tokens_used", 0
                            )
                            self.files_changed.extend(
                                refine_result.get("files_changed", [])
                            )
                            if refine_result.get("agent_summaries"):
                                self.agent_summaries = refine_result[
                                    "agent_summaries"
                                ]
                            if refine_result.get("final_decision"):
                                self.final_decision = refine_result[
                                    "final_decision"
                                ]
                            subtask_previous = {
                                **subtask_previous, **refine_result
                            }

                            # Re-verify with the feedback step
                            Display.phase(
                                "refine",
                                f"Round {round_num + 1}/{MAX_FEEDBACK_ROUNDS}: "
                                f"Re-verifying with {step.function}...",
                            )
                            verify_result = func(
                                prompt=subtask_prompt,
                                previous=subtask_previous,
                                step=step,
                                memory=self.memory,
                                config=self.config,
                                cwd=self.cwd,
                                cost_manager=self.cost_manager,
                            )
                            self.outputs.append(verify_result)
                            self.total_tokens += verify_result.get(
                                "tokens_used", 0
                            )
                            subtask_previous = {
                                **subtask_previous, **verify_result
                            }

                            if not _needs_refinement(verify_result):
                                Display.notify(
                                    f"{step.function} passed after "
                                    f"{round_num + 1} round(s)"
                                )
                                break

                            feedback_result = verify_result
                        else:
                            Display.notify(
                                f"Max feedback rounds "
                                f"({MAX_FEEDBACK_ROUNDS}) reached, "
                                f"continuing pipeline"
                            )

                self.steps_completed += 1
                Display.step_complete(step.function, step_result)
                Display.step_summary(step.function, step_result)

            except Exception as e:
                self.errors.append(
                    f"Subtask {task_num} - {step.function}: {str(e)}"
                )
                Display.step_error(step.function, str(e))
                break

        Display.notify(f"--- {title} complete ---")
        Display.set_task_label(None)

    def _run_subtasks_parallel(self, subtasks, remaining_steps,
                               previous_output, task_indices):
        """Run independent subtasks in parallel."""

        Display.notify(
            f"Running {len(subtasks)} independent subtasks in parallel..."
        )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(subtasks), 3)
        ) as executor:
            futures = {}
            for i, (subtask, task_idx) in enumerate(
                zip(subtasks, task_indices)
            ):
                future = executor.submit(
                    self._run_single_subtask,
                    subtask,
                    task_idx + 1,
                    len(subtasks),
                    remaining_steps,
                    previous_output,
                )
                futures[future] = task_idx

            for future in concurrent.futures.as_completed(futures):
                task_idx = futures[future]
                try:
                    future.result()
                except Exception as e:
                    self.errors.append(
                        f"Subtask {task_idx + 1} failed: {str(e)}"
                    )
                    Display.step_error(
                        "task", f"Subtask {task_idx + 1}: {str(e)}"
                    )

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

    def _run_archaeology(self):
        """Search previous runs for relevant context (Layer 2).

        Uses ContextArchaeologist to find relevant historical context
        and inject it into memory for downstream steps to use.
        """
        context_config = self.config.get("context", {})

        # Check if archaeology is enabled
        if not context_config.get("archaeology", True):
            return

        # Skip archaeology for simple pipelines
        if not self.steps:
            return

        # Find the .lion/runs directory
        runs_dir = os.path.join(self.cwd, ".lion", "runs")
        if not os.path.exists(runs_dir):
            return

        try:
            max_age_days = context_config.get("archaeology_max_age_days", 90)
            archaeologist = ContextArchaeologist(runs_dir, max_age_days)

            # Detect files that might be relevant
            files_involved = detect_relevant_files(self.prompt, self.cwd)

            # Find relevant previous runs
            max_results = context_config.get("archaeology_max_results", 3)
            relevant_runs = archaeologist.find_relevant_runs(
                prompt=self.prompt,
                files_involved=files_involved,
                max_results=max_results
            )

            if relevant_runs:
                # Format for injection
                max_tokens = context_config.get("archaeology_max_tokens", 500)
                history_context = archaeologist.format_for_prompt(
                    relevant_runs, max_tokens=max_tokens
                )

                if history_context:
                    # Inject into memory
                    self.memory.write(MemoryEntry(
                        timestamp=time.time(),
                        phase="archaeology",
                        agent="historian",
                        type="historical_context",
                        content=history_context,
                        metadata={
                            "runs_found": len(relevant_runs),
                            "run_ids": [os.path.basename(r["run_dir"]) for r in relevant_runs],
                        }
                    ))

                    Display.notify(
                        f"Found {len(relevant_runs)} relevant previous run(s) "
                        f"for context"
                    )

        except Exception as e:
            # Archaeology is best-effort, don't fail the pipeline
            Display.step_error("archaeology", f"Search failed: {str(e)}")
