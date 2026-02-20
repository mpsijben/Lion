"""Execute a parsed pipeline of steps."""

import time
from dataclasses import dataclass

from .parser import PipelineStep
from .memory import SharedMemory
from .display import Display
from .providers import get_provider
from .functions import FUNCTIONS


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

                previous_output = {**previous_output, **step_result}

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
