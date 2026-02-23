"""Textual TUI for live pipeline visualization and command-mode controls.

Implements all 11 TUI tasks from v0.1 roadmap:
1. Pipeline sidebar + active step panel
2. Streaming code output with syntax highlighting
3. Eye status widgets (checking/clean/finding)
4. Interrupt boxes
5. Tab navigation between steps
6. Command mode (:) with autocomplete
7. : inject -- manual correction to lead
8. : add/: remove -- add/remove steps
9. : eyes add/: eyes remove -- hot-swap eyes
10. : pause/: resume/: abort -- flow control
11. File tracker + diff view (f and d keys)
"""

from __future__ import annotations

import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from ..parser import PipelineStep, parse_lion_input
from .tui_bridge import (
    TUIBridge,
    PipelineStarted,
    StepStarted,
    StepCompleted,
    StepError,
    StepSummary,
    PhaseChanged,
    PairStarted,
    PairLeadChunk,
    PairCheckSubmitted,
    EyeFinding,
    PairInterrupt,
    EyeClean,
    PairCompleted,
    PairUsage,
    PreflightStarted,
    PreflightFinding,
    PreflightClean,
    EyeError,
    Notification,
    PipelineCompleted,
    AgentProposal,
    AgentCritique,
    Convergence,
)
from .tui_widgets import (
    PipelineSidebar,
    StepPanel,
    StepState,
    StepRow,
    StepSelected,
    CommandInput,
    CommandSubmitted,
    FileListWidget,
    FileSelected,
    FileChange,
    DiffOverlay,
)


# -- Reused classes from previous implementation -----------------------------


class FileTracker:
    """Monitors git status and provides per-file diffs."""

    def __init__(self, workdir: str = ".") -> None:
        self.workdir = workdir
        self.files: list[FileChange] = []

    def refresh(self) -> list[FileChange]:
        self.files = []
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=self.workdir,
            check=False,
        )
        if status.returncode != 0:
            return []

        for line in status.stdout.splitlines():
            if not line.strip():
                continue
            code = line[:2]
            path = line[3:].strip()
            parsed_status = self._parse_status(code)
            added, removed = self._diff_stats(path)
            self.files.append(
                FileChange(path=path, status=parsed_status, lines_added=added, lines_removed=removed)
            )

        self.files.sort(key=lambda f: f.path)
        return list(self.files)

    def get_diff(self, filepath: str) -> str:
        for cmd in (
            ["git", "diff", "--", filepath],
            ["git", "diff", "--cached", "--", filepath],
        ):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workdir,
                check=False,
            )
            if result.stdout:
                return result.stdout
        return ""

    def _diff_stats(self, filepath: str) -> tuple[int, int]:
        diff = subprocess.run(
            ["git", "diff", "--numstat", "--", filepath],
            capture_output=True,
            text=True,
            cwd=self.workdir,
            check=False,
        )
        if diff.stdout.strip():
            parts = diff.stdout.strip().split("\t")
            if len(parts) >= 2:
                add = 0 if parts[0] == "-" else int(parts[0])
                rem = 0 if parts[1] == "-" else int(parts[1])
                return add, rem

        file_path = Path(self.workdir) / filepath
        if file_path.exists() and file_path.is_file():
            try:
                return sum(1 for _ in file_path.open("r", encoding="utf-8")), 0
            except OSError:
                return 0, 0

        return 0, 0

    @staticmethod
    def _parse_status(code: str) -> str:
        code = code.strip() or "?"
        first = code[0]
        return {
            "A": "new",
            "?": "new",
            "M": "modified",
            "D": "deleted",
            "R": "renamed",
        }.get(first, "modified")


@dataclass
class ParsedCommand:
    action: str
    args: dict[str, str] = field(default_factory=dict)


class CommandModeParser:
    """Parser for ':' command-mode pipeline edits and flow controls."""

    @staticmethod
    def parse(raw: str) -> ParsedCommand:
        text = raw.strip()
        if text.startswith(":"):
            text = text[1:].strip()
        if not text:
            return ParsedCommand(action="noop")

        lowered = text.lower()
        if lowered.startswith("inject "):
            return ParsedCommand(action="inject", args={"message": text[7:].strip().strip('"\'')})

        if lowered in {"pause", "resume", "abort"}:
            return ParsedCommand(action=lowered)

        if lowered.startswith("eyes "):
            parts = shlex.split(text)
            sub = parts[1] if len(parts) > 1 else ""
            lens = parts[2] if len(parts) > 2 else ""
            if sub in {"add", "remove", "list"}:
                return ParsedCommand(action=f"eyes_{sub}", args={"lens": lens})

        if lowered.startswith("add ") and (" after " in lowered or " before " in lowered):
            marker = " after " if " after " in lowered else " before "
            step_def, _, target = text[4:].partition(marker)
            return ParsedCommand(
                action="add_step",
                args={
                    "step": step_def.strip(),
                    "position": marker.strip(),
                    "target": target.strip(),
                },
            )

        if lowered.startswith("remove "):
            return ParsedCommand(action="remove_step", args={"target": text[7:].strip()})

        return ParsedCommand(action="unknown", args={"raw": text})


class PairControl:
    """Thread-safe runtime controls for pair() command-mode actions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._injections: list[str] = []
        self._pending_add_eyes: list[str] = []
        self._pending_remove_eyes: list[str] = []
        self._paused = False
        self._aborted = False

    def inject(self, message: str) -> None:
        with self._lock:
            if message.strip():
                self._injections.append(message.strip())

    def pop_injections(self) -> list[str]:
        with self._lock:
            items = list(self._injections)
            self._injections.clear()
            return items

    def add_eye(self, lens: str) -> None:
        with self._lock:
            self._pending_add_eyes.append(lens.strip())

    def remove_eye(self, lens: str) -> None:
        with self._lock:
            self._pending_remove_eyes.append(lens.strip())

    def pop_eye_mutations(self) -> tuple[list[str], list[str]]:
        with self._lock:
            add = list(self._pending_add_eyes)
            remove = list(self._pending_remove_eyes)
            self._pending_add_eyes.clear()
            self._pending_remove_eyes.clear()
            return add, remove

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def abort(self) -> None:
        with self._lock:
            self._aborted = True

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def aborted(self) -> bool:
        with self._lock:
            return self._aborted


# -- Textual App -------------------------------------------------------------


class LionApp(App):
    """Textual TUI for live pipeline visualization."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-area {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("tab", "next_step", "Next step", show=True),
        Binding("shift+tab", "prev_step", "Prev step", show=True),
        Binding("f", "toggle_files", "Files", show=True, priority=False),
        Binding("d", "show_diff", "Diff", show=True, priority=False),
        Binding("i", "toggle_interrupts", "Interrupts", show=False, priority=False),
        Binding("q", "quit_or_back", "Quit", show=True, priority=False),
        Binding("c", "copy_output", "Copy", show=False, priority=False),
    ]

    def __init__(
        self,
        prompt: str,
        steps: list[PipelineStep],
        config: dict | None = None,
        run_dir: str | None = None,
        executor: Any = None,
    ) -> None:
        super().__init__()
        self.prompt = prompt
        self.pipeline_steps = steps
        self.config = config or {}
        self.run_dir = run_dir
        self.executor = executor

        # Build step states from pipeline steps
        self.step_states = [
            StepState(name=self._step_label(step))
            for step in steps
        ]
        self.active_index = 0
        self.pair_control = PairControl()
        self.file_tracker = FileTracker()
        self.bridge = TUIBridge(self)
        self._pipeline_result = None
        self._interrupt_count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield PipelineSidebar(self.step_states)
        with Vertical(id="main-area"):
            yield StepPanel(self.step_states[0] if self.step_states else None)
            yield FileListWidget()
        yield CommandInput()
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"Lion -- {self.prompt[:60]}"
        self.sub_title = f"{len(self.step_states)} steps"
        # Install bridge and start pipeline in background
        self.bridge.install()
        if self.executor:
            self.run_worker(self._run_pipeline, thread=True)

    def on_unmount(self) -> None:
        self.bridge.uninstall()

    # -- Pipeline execution (runs in worker thread) --------------------------

    def _run_pipeline(self) -> None:
        """Execute the pipeline. Runs on a worker thread."""
        try:
            if self.executor:
                result = self.executor()
                self.post_message(PipelineCompleted(result))
        except Exception as e:
            self.post_message(Notification(f"Pipeline error: {e}"))

    # -- Message handlers (bridge events -> widget updates) ------------------

    def on_step_started(self, event: StepStarted) -> None:
        idx = event.num - 1  # 1-indexed to 0-indexed
        if 0 <= idx < len(self.step_states):
            self.step_states[idx].status = "active"
            self.active_index = idx
            self._refresh_sidebar()
            self._switch_to_step(idx)

    def on_step_completed(self, event: StepCompleted) -> None:
        idx = self._find_step(event.func_name)
        if idx >= 0:
            self.step_states[idx].status = "done"
            self._refresh_sidebar()

    def on_step_error(self, event: StepError) -> None:
        idx = self._find_step(event.func_name)
        if idx >= 0:
            self.step_states[idx].status = "failed"
            panel = self.query_one(StepPanel)
            panel.append_output(f"\n[red]ERROR: {event.error}[/red]\n")
            self._refresh_sidebar()

    def on_pair_started(self, event: PairStarted) -> None:
        # Initialize eye statuses for the active step
        step = self._active_step()
        if step:
            for label in event.eye_labels:
                step.eye_statuses[label] = "waiting"
            panel = self.query_one(StepPanel)
            panel.query_one("EyeStatusBar").update_eyes(step.eye_statuses)

    def on_pair_lead_chunk(self, event: PairLeadChunk) -> None:
        step = self._active_step()
        if step:
            step.output.append(event.text)
            step.lines += event.text.count("\n")
            panel = self.query_one(StepPanel)
            panel.append_output(event.text)
            self._refresh_sidebar()

    def on_pair_check_submitted(self, event: PairCheckSubmitted) -> None:
        step = self._active_step()
        if step:
            for name in step.eye_statuses:
                step.eye_statuses[name] = "checking"
            panel = self.query_one(StepPanel)
            panel.query_one("EyeStatusBar").update_eyes(step.eye_statuses)

    def on_eye_finding(self, event: EyeFinding) -> None:
        step = self._active_step()
        if step:
            step.eye_statuses[event.eye_name] = f"finding: {event.lens}"
            self._interrupt_count += 1
            step.interrupt_log.append({
                "eye_name": event.eye_name,
                "lens": event.lens,
                "description": event.description,
                "latency": event.latency,
                "count": self._interrupt_count,
            })
            panel = self.query_one(StepPanel)
            panel.add_interrupt(event.eye_name, event.lens, event.description,
                                event.latency, self._interrupt_count)
            panel.query_one("EyeStatusBar").set_eye(event.eye_name, f"finding: {event.lens}")

    def on_pair_interrupt(self, event: PairInterrupt) -> None:
        step = self._active_step()
        if step:
            step.interrupts = event.count
            panel = self.query_one(StepPanel)
            panel.append_output("\n>>> Resuming with correction...\n\n")
            self._refresh_sidebar()

    def on_eye_clean(self, event: EyeClean) -> None:
        step = self._active_step()
        if step:
            for name in step.eye_statuses:
                step.eye_statuses[name] = "clean"
            panel = self.query_one(StepPanel)
            panel.query_one("EyeStatusBar").update_eyes(step.eye_statuses)

    def on_pair_completed(self, event: PairCompleted) -> None:
        step = self._active_step()
        if step:
            step.elapsed = event.wall_clock
            step.lines = event.lines

    def on_pair_usage(self, event: PairUsage) -> None:
        panel = self.query_one(StepPanel)
        cost_str = f"${event.total_cost:.4f}" if event.total_cost > 0 else f"{event.total_tokens:,} tokens"
        panel.append_output(f"\n[dim]Usage: {event.total_tokens:,} tokens - {cost_str}[/dim]\n")

    def on_preflight_started(self, event: PreflightStarted) -> None:
        panel = self.query_one(StepPanel)
        panel.append_output(f"[dim]Preflight: {event.num_eyes} eye(s) checking...[/dim]\n")

    def on_preflight_finding(self, event: PreflightFinding) -> None:
        self.on_eye_finding(EyeFinding(event.eye_name, event.lens, event.description, event.latency))

    def on_preflight_clean(self, event: PreflightClean) -> None:
        panel = self.query_one(StepPanel)
        panel.append_output("[green]Preflight clean[/green]\n\n")

    def on_eye_error(self, event: EyeError) -> None:
        step = self._active_step()
        if step:
            step.eye_statuses[event.eye_name] = "error"
            panel = self.query_one(StepPanel)
            panel.query_one("EyeStatusBar").set_eye(event.eye_name, "error")

    def on_notification(self, event: Notification) -> None:
        panel = self.query_one(StepPanel)
        panel.append_output(f"[dim]{event.text}[/dim]\n")

    def on_phase_changed(self, event: PhaseChanged) -> None:
        panel = self.query_one(StepPanel)
        panel.append_output(f"\n[bold]{event.name.upper()}[/bold]: {event.description}\n")

    def on_agent_proposal(self, event: AgentProposal) -> None:
        panel = self.query_one(StepPanel)
        lens_label = f"::{event.lens.shortcode}" if event.lens else ""
        preview = event.preview.replace("\n", " ")[:120]
        panel.append_output(f"  Agent {event.num} ({event.model}{lens_label}): [dim]{preview}...[/dim]\n")

    def on_agent_critique(self, event: AgentCritique) -> None:
        panel = self.query_one(StepPanel)
        preview = event.preview.replace("\n", " ")[:120]
        panel.append_output(f"  Critique {event.num}: [dim]{preview}...[/dim]\n")

    def on_convergence(self, event: Convergence) -> None:
        panel = self.query_one(StepPanel)
        preview = event.preview.replace("\n", " ")[:200]
        panel.append_output(f"\n  [green]Consensus:[/green] [dim]{preview}...[/dim]\n")

    def on_pipeline_completed(self, event: PipelineCompleted) -> None:
        self._pipeline_result = event.result
        self.sub_title = "DONE"
        # Mark any still-active steps as done
        for step in self.step_states:
            if step.status == "active":
                step.status = "done"
        self._refresh_sidebar()
        # Refresh file tracker
        files = self.file_tracker.refresh()
        if files:
            step = self._active_step()
            if step:
                step.files_changed = files
            panel = self.query_one(StepPanel)
            panel.update_files(files)
            panel._update_header()
            self.query_one(FileListWidget).update_files(files)

    # -- Widget event handlers -----------------------------------------------

    def on_step_selected(self, event: StepSelected) -> None:
        self._switch_to_step(event.index)

    def on_command_submitted(self, event: CommandSubmitted) -> None:
        parsed = CommandModeParser.parse(event.command)
        self._execute_command(parsed)

    def on_file_selected(self, event: FileSelected) -> None:
        diff_text = self.file_tracker.get_diff(event.path)
        self.push_screen(DiffOverlay(event.path, diff_text))

    # -- Key bindings (Task 5: Tab navigation, Task 11: f/d keys) ------------

    def action_next_step(self) -> None:
        if self.step_states:
            self.active_index = (self.active_index + 1) % len(self.step_states)
            self._switch_to_step(self.active_index)

    def action_prev_step(self) -> None:
        if self.step_states:
            self.active_index = (self.active_index - 1) % len(self.step_states)
            self._switch_to_step(self.active_index)

    def action_toggle_files(self) -> None:
        file_widget = self.query_one(FileListWidget)
        # Refresh files before showing
        files = self.file_tracker.refresh()
        step = self._active_step()
        if step:
            step.files_changed = files
        file_widget.update_files(files)
        file_widget.toggle()

    def action_show_diff(self) -> None:
        file_widget = self.query_one(FileListWidget)
        if file_widget._files and file_widget._selected < len(file_widget._files):
            path = file_widget._files[file_widget._selected].path
            diff_text = self.file_tracker.get_diff(path)
            self.push_screen(DiffOverlay(path, diff_text))

    def action_toggle_interrupts(self) -> None:
        # Scroll to interrupts in the step panel
        step = self._active_step()
        if step and step.interrupt_log:
            panel = self.query_one(StepPanel)
            panel.append_output(f"\n[yellow]--- Interrupt History ({len(step.interrupt_log)}) ---[/yellow]\n")
            for finding in step.interrupt_log:
                panel.append_output(
                    f"  #{finding['count']} [{finding['eye_name']}] "
                    f"[{finding['lens']}] {finding['description']} "
                    f"({finding['latency']:.1f}s)\n"
                )

    def on_key(self, event) -> None:
        """Handle ':' for command mode only when Input is not focused."""
        from textual.widgets import Input as TextualInput
        if event.character == ":" and not isinstance(self.focused, TextualInput):
            self.query_one(CommandInput).show()
            event.stop()

    def action_quit_or_back(self) -> None:
        if self.pair_control:
            self.pair_control.abort()
        self.exit()

    def action_copy_output(self) -> None:
        step = self._active_step()
        if step:
            import pyperclip
            try:
                pyperclip.copy("".join(step.output))
                self.notify("Output copied to clipboard")
            except Exception:
                self.notify("Could not copy to clipboard", severity="error")

    # -- Command execution (Tasks 6-10) --------------------------------------

    def _execute_command(self, parsed: ParsedCommand) -> None:
        if parsed.action == "inject":
            self.pair_control.inject(parsed.args.get("message", ""))
            self.notify(f"Injected: {parsed.args.get('message', '')[:50]}")
        elif parsed.action == "pause":
            self.pair_control.pause()
            step = self._active_step()
            if step:
                step.status = "paused"
            self._refresh_sidebar()
            self.notify("Paused")
        elif parsed.action == "resume":
            self.pair_control.resume()
            step = self._active_step()
            if step:
                step.status = "active"
            self._refresh_sidebar()
            self.notify("Resumed")
        elif parsed.action == "abort":
            self.pair_control.abort()
            step = self._active_step()
            if step:
                step.status = "aborted"
            self._refresh_sidebar()
            self.notify("Aborted")
        elif parsed.action == "eyes_add":
            self.pair_control.add_eye(parsed.args.get("lens", ""))
            self.notify(f"Eye added: {parsed.args.get('lens', '')}")
        elif parsed.action == "eyes_remove":
            self.pair_control.remove_eye(parsed.args.get("lens", ""))
            self.notify(f"Eye removed: {parsed.args.get('lens', '')}")
        elif parsed.action == "eyes_list":
            step = self._active_step()
            if step:
                eyes_str = ", ".join(f"{k}: {v}" for k, v in step.eye_statuses.items())
                self.notify(f"Eyes: {eyes_str}")
        elif parsed.action == "add_step":
            step_text = parsed.args.get("step", "")
            target = parsed.args.get("target", "")
            position = parsed.args.get("position", "after")
            try:
                new_pipeline_step = self._parse_single_step(step_text)
                idx = self._find_step_by_name(target)
                insert_at = idx + 1 if position == "after" else idx
                new_state = StepState(name=self._step_label(new_pipeline_step))
                self.step_states.insert(insert_at, new_state)
                self._rebuild_sidebar()
                self.notify(f"Added {step_text} {position} {target}")
            except ValueError as e:
                self.notify(f"Error: {e}", severity="error")
        elif parsed.action == "remove_step":
            target = parsed.args.get("target", "")
            idx = self._find_step_by_name(target)
            if idx >= 0:
                self.step_states.pop(idx)
                self.active_index = min(self.active_index, max(0, len(self.step_states) - 1))
                self._rebuild_sidebar()
                self.notify(f"Removed {target}")
            else:
                self.notify(f"Step not found: {target}", severity="error")
        elif parsed.action == "unknown":
            self.notify(f"Unknown command: {parsed.args.get('raw', '')}", severity="error")

    # -- Helpers -------------------------------------------------------------

    def _active_step(self) -> StepState | None:
        if 0 <= self.active_index < len(self.step_states):
            return self.step_states[self.active_index]
        return None

    def _find_step(self, func_name: str) -> int:
        """Find step index by function name."""
        for i, step in enumerate(self.step_states):
            if step.name.lower().startswith(func_name.lower()):
                return i
        return -1

    def _find_step_by_name(self, name: str) -> int:
        name = name.strip().lower()
        for i, step in enumerate(self.step_states):
            if step.name.lower().startswith(name):
                return i
        return -1

    def _switch_to_step(self, index: int) -> None:
        if 0 <= index < len(self.step_states):
            self.active_index = index
            sidebar = self.query_one(PipelineSidebar)
            sidebar.active_index = index
            panel = self.query_one(StepPanel)
            panel.set_step(self.step_states[index])

    def _refresh_sidebar(self) -> None:
        sidebar = self.query_one(PipelineSidebar)
        sidebar.refresh_steps()

    def _rebuild_sidebar(self) -> None:
        """Rebuild sidebar after add/remove step."""
        old = self.query_one(PipelineSidebar)
        new_sidebar = PipelineSidebar(self.step_states)
        old.remove()
        self.mount(new_sidebar, before=self.query_one("#main-area"))

    def _parse_single_step(self, step_str: str) -> PipelineStep:
        _, steps = parse_lion_input(f'"_" -> {step_str}')
        if not steps:
            raise ValueError(f"Invalid step: {step_str}")
        return steps[0]

    @staticmethod
    def _step_label(step: PipelineStep) -> str:
        if step.args and step.kwargs:
            arg_str = ", ".join(str(a) for a in step.args)
            kw_str = ", ".join(f"{k}: {v}" for k, v in step.kwargs.items())
            return f"{step.function}({arg_str}, {kw_str})"
        if step.args:
            arg_str = ", ".join(str(a) for a in step.args)
            return f"{step.function}({arg_str})"
        if step.kwargs:
            kw_str = ", ".join(f"{k}: {v}" for k, v in step.kwargs.items())
            return f"{step.function}({kw_str})"
        if step.function in {"pair", "fuse", "review", "impl"}:
            return f"{step.function}()"
        return step.function
