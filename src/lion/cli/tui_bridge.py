"""Bridge between Display callbacks and Textual message passing.

When the TUI is active, Display methods are monkey-patched to post
Textual messages instead of printing to the terminal. This means
pipeline.py, pair.py, pride.py etc. need zero changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.message import Message

from ..display import Display


# -- Textual Messages --------------------------------------------------------
# Each Display method maps to a message class that widgets can handle.


class PipelineStarted(Message):
    def __init__(self, prompt: str, steps: list) -> None:
        super().__init__()
        self.prompt = prompt
        self.steps = steps


class StepStarted(Message):
    def __init__(self, num: int, total: int, step: Any, concurrent: bool = False) -> None:
        super().__init__()
        self.num = num
        self.total = total
        self.step = step
        self.concurrent = concurrent


class StepCompleted(Message):
    def __init__(self, func_name: str, result: dict, concurrent: bool = False) -> None:
        super().__init__()
        self.func_name = func_name
        self.result = result
        self.concurrent = concurrent


class StepError(Message):
    def __init__(self, func_name: str, error: str) -> None:
        super().__init__()
        self.func_name = func_name
        self.error = error


class StepSummary(Message):
    def __init__(self, func_name: str, result: dict, concurrent: bool = False) -> None:
        super().__init__()
        self.func_name = func_name
        self.result = result
        self.concurrent = concurrent


class PhaseChanged(Message):
    def __init__(self, name: str, description: str) -> None:
        super().__init__()
        self.name = name
        self.description = description


class PairStarted(Message):
    def __init__(self, lead_name: str, eye_labels: list[str]) -> None:
        super().__init__()
        self.lead_name = lead_name
        self.eye_labels = eye_labels


class PairLeadChunk(Message):
    def __init__(self, lead_name: str, text: str) -> None:
        super().__init__()
        self.lead_name = lead_name
        self.text = text


class PairCheckSubmitted(Message):
    def __init__(self, check_num: int, total_lines: int, elapsed: float) -> None:
        super().__init__()
        self.check_num = check_num
        self.total_lines = total_lines
        self.elapsed = elapsed


class EyeFinding(Message):
    def __init__(self, eye_name: str, lens: str, description: str, latency: float) -> None:
        super().__init__()
        self.eye_name = eye_name
        self.lens = lens
        self.description = description
        self.latency = latency


class PairInterrupt(Message):
    def __init__(self, count: int, total_findings: int, preflight: bool = False) -> None:
        super().__init__()
        self.count = count
        self.total_findings = total_findings
        self.preflight = preflight


class EyeClean(Message):
    def __init__(self, num_eyes: int) -> None:
        super().__init__()
        self.num_eyes = num_eyes


class PairCompleted(Message):
    def __init__(self, interrupts: int, wall_clock: float, lines: int) -> None:
        super().__init__()
        self.interrupts = interrupts
        self.wall_clock = wall_clock
        self.lines = lines


class PairUsage(Message):
    def __init__(self, lead_usage: dict, eye_usage_list: list, total_tokens: int, total_cost: float) -> None:
        super().__init__()
        self.lead_usage = lead_usage
        self.eye_usage_list = eye_usage_list
        self.total_tokens = total_tokens
        self.total_cost = total_cost


class PreflightStarted(Message):
    def __init__(self, num_eyes: int, thinking_lines: int = 0) -> None:
        super().__init__()
        self.num_eyes = num_eyes
        self.thinking_lines = thinking_lines


class PreflightFinding(Message):
    def __init__(self, eye_name: str, lens: str, description: str, latency: float) -> None:
        super().__init__()
        self.eye_name = eye_name
        self.lens = lens
        self.description = description
        self.latency = latency


class PreflightClean(Message):
    pass


class EyeError(Message):
    def __init__(self, eye_name: str, error: str) -> None:
        super().__init__()
        self.eye_name = eye_name
        self.error = error


class Notification(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class PipelineCompleted(Message):
    def __init__(self, result: Any) -> None:
        super().__init__()
        self.result = result


class AgentProposal(Message):
    def __init__(self, num: int, model: str, preview: str, lens: Any = None) -> None:
        super().__init__()
        self.num = num
        self.model = model
        self.preview = preview
        self.lens = lens


class AgentCritique(Message):
    def __init__(self, num: int, preview: str, lens: Any = None) -> None:
        super().__init__()
        self.num = num
        self.preview = preview
        self.lens = lens


class Convergence(Message):
    def __init__(self, preview: str) -> None:
        super().__init__()
        self.preview = preview


# -- Bridge ------------------------------------------------------------------


class TUIBridge:
    """Patches Display methods to post Textual messages when TUI is active."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._originals: dict[str, Any] = {}

    def install(self) -> None:
        """Monkey-patch Display class methods to route to Textual messages."""
        app = self.app  # capture for closures

        self._patch("pipeline_start",
                     lambda prompt, steps: app.post_message(PipelineStarted(prompt, steps)))
        self._patch("step_start",
                     lambda num, total, step, concurrent=False: app.post_message(
                         StepStarted(num, total, step, concurrent)))
        self._patch("step_complete",
                     lambda func_name, result, concurrent=False: app.post_message(
                         StepCompleted(func_name, result, concurrent)))
        self._patch("step_error",
                     lambda func_name, error: app.post_message(StepError(func_name, error)))
        self._patch("step_summary",
                     lambda func_name, result, concurrent=False: app.post_message(
                         StepSummary(func_name, result, concurrent)))
        self._patch("phase",
                     lambda name, description: app.post_message(PhaseChanged(name, description)))
        self._patch("pair_start",
                     lambda lead_name, eye_labels: app.post_message(
                         PairStarted(lead_name, eye_labels)))
        self._patch("pair_lead_chunk",
                     lambda lead_name, text: app.post_message(PairLeadChunk(lead_name, text)))
        self._patch("pair_check_submitted",
                     lambda check_num, total_lines, elapsed: app.post_message(
                         PairCheckSubmitted(check_num, total_lines, elapsed)))
        self._patch("pair_finding",
                     lambda eye_name, lens, description, latency: app.post_message(
                         EyeFinding(eye_name, lens, description, latency)))
        self._patch("pair_interrupt",
                     lambda count, total_findings, preflight=False: app.post_message(
                         PairInterrupt(count, total_findings, preflight)))
        self._patch("pair_clean",
                     lambda num_eyes: app.post_message(EyeClean(num_eyes)))
        self._patch("pair_complete",
                     lambda interrupts, wall_clock, lines: app.post_message(
                         PairCompleted(interrupts, wall_clock, lines)))
        self._patch("pair_usage",
                     lambda lead_usage, eye_usage_list, total_tokens, total_cost: app.post_message(
                         PairUsage(lead_usage, eye_usage_list, total_tokens, total_cost)))
        self._patch("pair_preflight_started",
                     lambda num_eyes, thinking_lines=0: app.post_message(
                         PreflightStarted(num_eyes, thinking_lines)))
        self._patch("pair_preflight_finding",
                     lambda eye_name, lens, description, latency: app.post_message(
                         PreflightFinding(eye_name, lens, description, latency)))
        self._patch("pair_preflight_clean",
                     lambda: app.post_message(PreflightClean()))
        self._patch("pair_eye_error",
                     lambda eye_name, error: app.post_message(EyeError(eye_name, error)))
        self._patch("notify",
                     lambda message: app.post_message(Notification(message)))
        self._patch("agent_proposal",
                     lambda num, model, preview, lens=None: app.post_message(
                         AgentProposal(num, model, preview, lens)))
        self._patch("agent_critique",
                     lambda num, preview, lens=None: app.post_message(
                         AgentCritique(num, preview, lens)))
        self._patch("convergence",
                     lambda preview: app.post_message(Convergence(preview)))

    def uninstall(self) -> None:
        """Restore original Display methods."""
        for name, original in self._originals.items():
            setattr(Display, name, original)
        self._originals.clear()

    def _patch(self, method_name: str, replacement: Any) -> None:
        self._originals[method_name] = getattr(Display, method_name)
        setattr(Display, method_name, staticmethod(replacement))
