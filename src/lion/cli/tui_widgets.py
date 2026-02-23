"""Custom Textual widgets for the Lion TUI.

Covers all 11 TUI tasks from the v0.1 roadmap:
1. PipelineSidebar - pipeline sidebar + active step panel
2. StepPanel - streaming code output with syntax highlighting
3. EyeStatusBar - eye status widgets
4. InterruptBox - interrupt boxes
5. Tab navigation (handled by LionApp bindings)
6-10. CommandInput - command mode with all : commands
11. FileListWidget + DiffOverlay - file tracker + diff view
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Input,
    RichLog,
    Static,
)

from rich.syntax import Syntax
from rich.text import Text


# -- Data classes (reused from old tui.py) -----------------------------------


@dataclass
class FileChange:
    path: str
    status: str
    lines_added: int = 0
    lines_removed: int = 0


@dataclass
class StepState:
    """Per-step state tracked by the TUI."""
    name: str
    status: str = "waiting"  # waiting|active|done|failed|paused|aborted
    elapsed: float = 0.0
    interrupts: int = 0
    lines: int = 0
    output: list[str] = field(default_factory=list)
    eye_statuses: dict[str, str] = field(default_factory=dict)
    interrupt_log: list[dict] = field(default_factory=list)
    files_changed: list[FileChange] = field(default_factory=list)


# -- Status icons ------------------------------------------------------------

STATUS_ICONS = {
    "waiting": "\u25cb",   # ○
    "active": "\u25cf",    # ●
    "done": "\u2705",      # ✅
    "failed": "\u274c",    # ❌
    "paused": "\u23f8",    # ⏸
    "aborted": "\u23f9",   # ⏹
}


# -- Pipeline Sidebar (Task 1) ----------------------------------------------


class StepSelected(Message):
    """Posted when user clicks a step in the sidebar."""
    def __init__(self, index: int) -> None:
        super().__init__()
        self.index = index


class PipelineSidebar(Widget):
    """Vertical list of pipeline steps with status icons."""

    DEFAULT_CSS = """
    PipelineSidebar {
        dock: top;
        height: auto;
        max-height: 12;
        border: solid $accent;
        padding: 0 1;
    }
    PipelineSidebar .step-row {
        height: 1;
    }
    PipelineSidebar .step-row.active {
        background: $boost;
    }
    """

    BORDER_TITLE = "Pipeline"

    active_index: reactive[int] = reactive(0)

    def __init__(self, steps: list[StepState]) -> None:
        super().__init__()
        self.steps = steps

    def compose(self) -> ComposeResult:
        for i, step in enumerate(self.steps):
            yield StepRow(step, index=i)

    def watch_active_index(self, value: int) -> None:
        for i, row in enumerate(self.query(StepRow)):
            row.set_class(i == value, "active")

    def refresh_steps(self) -> None:
        """Update all step rows to reflect current state."""
        for row in self.query(StepRow):
            row.update_display()


class StepRow(Static):
    """Single row in the pipeline sidebar."""

    DEFAULT_CSS = """
    StepRow {
        height: 1;
        padding: 0 1;
    }
    StepRow.active {
        background: $boost;
    }
    """

    def __init__(self, step: StepState, index: int) -> None:
        super().__init__()
        self.step = step
        self.index = index

    def render(self) -> Text:
        icon = STATUS_ICONS.get(self.step.status, "\u25cb")
        text = Text()
        text.append(f"{icon} ", style="bold")
        text.append(self.step.name, style="bold" if self.step.status == "active" else "")

        meta = []
        if self.step.elapsed:
            meta.append(f"{self.step.elapsed:.0f}s")
        if self.step.interrupts:
            suffix = "interrupt" if self.step.interrupts == 1 else "interrupts"
            meta.append(f"{self.step.interrupts} {suffix}")
        if self.step.lines:
            meta.append(f"{self.step.lines} lines")
        if meta:
            text.append("  ")
            text.append("  ".join(meta), style="dim")

        return text

    def update_display(self) -> None:
        self.refresh()

    async def on_click(self) -> None:
        self.post_message(StepSelected(self.index))


# -- Step Panel (Tasks 1, 2, 4) ---------------------------------------------


class CodeBlock(Static):
    """A single syntax-highlighted code block that can be scrolled independently."""

    DEFAULT_CSS = """
    CodeBlock {
        height: auto;
        margin: 0 0 1 0;
        border: solid $accent-darken-1;
        padding: 0 1;
        overflow-y: auto;
        max-height: 20;
    }
    """

    def __init__(self, code: str, language: str = "", block_num: int = 0) -> None:
        super().__init__()
        self.code = code
        self.language = language
        self.block_num = block_num
        self.border_title = f"{language}" if language else f"code #{block_num}"

    def render(self) -> Text:
        if self.language:
            try:
                syntax = Syntax(
                    self.code, self.language,
                    theme="monokai", line_numbers=True,
                    word_wrap=True,
                )
                # Syntax objects render via Rich protocol; wrap as Text for Static
                from rich.console import Console
                from io import StringIO
                buf = StringIO()
                console = Console(file=buf, force_terminal=True, width=120)
                console.print(syntax)
                return Text.from_ansi(buf.getvalue())
            except Exception:
                pass
        return Text(self.code)


class StepPanel(Widget):
    """Main content area: streams output into separate code blocks.

    Incoming text is buffered and split on fenced code block markers
    (``` ... ```). Each code block becomes a separate scrollable
    CodeBlock widget with syntax highlighting. Non-code text appears
    as regular Static labels between blocks. The eye status bar sits
    at the top.
    """

    DEFAULT_CSS = """
    StepPanel {
        height: 1fr;
        layout: vertical;
    }
    StepPanel #step-header {
        height: auto;
        max-height: 3;
        border-bottom: solid $accent-darken-2;
        padding: 0 1;
    }
    StepPanel #output-scroll {
        height: 1fr;
        padding: 0 1;
    }
    StepPanel EyeStatusBar {
        height: auto;
        dock: bottom;
    }
    StepPanel .text-block {
        height: auto;
        padding: 0;
        margin: 0 0 0 0;
    }
    StepPanel .interrupt-marker {
        height: auto;
        padding: 0 1;
        background: $warning 15%;
        border: solid $warning;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, step: StepState | None = None) -> None:
        super().__init__()
        self.step = step
        self._buffer = ""          # Accumulates raw text between flushes
        self._pending_text = ""    # Accumulates plain text between code blocks
        self._in_code_block = False
        self._code_lang = ""
        self._code_lines: list[str] = []
        self._block_count = 0
        self._widget_count = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="step-header")
        yield VerticalScroll(id="output-scroll")
        yield EyeStatusBar()

    def on_mount(self) -> None:
        self._update_header()

    def set_step(self, step: StepState) -> None:
        """Switch to showing a different step."""
        self.step = step
        self._reset_parser()
        scroll = self.query_one("#output-scroll", VerticalScroll)
        scroll.remove_children()
        # Re-parse all existing output to rebuild blocks
        full_output = "".join(step.output)
        if full_output:
            self._process_text(full_output)
        # Update eye statuses
        eye_bar = self.query_one(EyeStatusBar)
        eye_bar.update_eyes(step.eye_statuses)
        self._update_header()

    def append_output(self, text: str) -> None:
        """Append streaming output (incremental). Parses for code blocks."""
        if self.step:
            self._process_text(text)
            self._scroll_to_bottom()

    def add_interrupt(self, eye_name: str, lens: str, description: str,
                      latency: float, count: int) -> None:
        """Add an interrupt marker between code blocks."""
        # Flush any pending text/code first
        self._flush_buffer()
        self._flush_code_block()
        # Add interrupt marker widget
        marker_text = Text()
        marker_text.append(f"INTERRUPT #{count} ", style="bold yellow")
        marker_text.append(f"[{eye_name}] ", style="bold")
        marker_text.append(f"[{lens}] ", style="cyan")
        marker_text.append(description[:100], style="")
        if latency:
            marker_text.append(f" ({latency:.1f}s)", style="dim")
        self._mount_widget(Static(marker_text, classes="interrupt-marker"))

    def update_files(self, files: list[FileChange]) -> None:
        """Update file change info (stored on step, no separate panel)."""
        if self.step:
            self.step.files_changed = files

    # -- Streaming parser -------------------------------------------------------

    def _process_text(self, text: str) -> None:
        """Process incoming text, splitting on ``` fences."""
        self._buffer += text
        while "\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition("\n")
            self._process_line(line + "\n")
        # Don't flush partial lines - wait for newline

    def _process_line(self, line: str) -> None:
        """Process a single line, detecting code fence boundaries."""
        stripped = line.strip()

        # Detect code fence opening: ```language or just ```
        if stripped.startswith("```") and not self._in_code_block:
            # Flush any pending plain text
            self._flush_text_block()
            # Start a new code block
            self._in_code_block = True
            lang = stripped[3:].strip()
            self._code_lang = lang if lang else ""
            self._code_lines = []
            return

        # Detect code fence closing: ``` on its own line
        if stripped == "```" and self._in_code_block:
            self._flush_code_block()
            self._in_code_block = False
            return

        # Accumulate into current block
        if self._in_code_block:
            self._code_lines.append(line)
        else:
            self._pending_text = self._pending_text + line
            # Flush plain text periodically so it shows up during streaming
            if self._pending_text.count("\n") >= 5:
                self._flush_text_block()

    def _flush_text_block(self) -> None:
        """Flush accumulated plain text as a Static widget."""
        text = self._pending_text
        if text.strip():
            self._mount_widget(
                Static(text.rstrip(), classes="text-block", markup=True)
            )
        self._pending_text = ""

    def _flush_code_block(self) -> None:
        """Flush accumulated code lines as a CodeBlock widget."""
        if not self._code_lines:
            return
        self._block_count += 1
        code = "".join(self._code_lines).rstrip("\n")
        block = CodeBlock(code, self._code_lang, self._block_count)
        self._mount_widget(block)
        self._code_lines = []
        self._code_lang = ""

    def _flush_buffer(self) -> None:
        """Flush any remaining buffer content."""
        if self._buffer.strip():
            if self._in_code_block:
                self._code_lines.append(self._buffer)
            else:
                self._pending_text = self._pending_text + self._buffer
        self._buffer = ""
        self._flush_text_block()

    def _mount_widget(self, widget: Widget) -> None:
        """Mount a widget into the output scroll area."""
        self._widget_count += 1
        scroll = self.query_one("#output-scroll", VerticalScroll)
        scroll.mount(widget)

    def _scroll_to_bottom(self) -> None:
        """Scroll to bottom of output area."""
        try:
            scroll = self.query_one("#output-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    def _reset_parser(self) -> None:
        """Reset the streaming parser state."""
        self._buffer = ""
        self._in_code_block = False
        self._code_lang = ""
        self._code_lines = []
        self._block_count = 0
        self._widget_count = 0
        self._pending_text = ""

    def _update_header(self) -> None:
        header = self.query_one("#step-header", Static)
        if self.step:
            icon = STATUS_ICONS.get(self.step.status, "\u25cb")
            title = f"{icon} {self.step.name}"
            if self.step.status == "active":
                title += " -- streaming..."
            elif self.step.status == "done" and self.step.lines:
                title += f" -- {self.step.lines} lines"
            if self.step.files_changed:
                title += f"  |  {len(self.step.files_changed)} files changed"
            header.update(title)
        else:
            header.update("No step selected")


# -- Eye Status Bar (Task 3) ------------------------------------------------


class EyeStatusBar(Widget):
    """Horizontal bar showing eye agent statuses."""

    DEFAULT_CSS = """
    EyeStatusBar {
        height: auto;
        max-height: 3;
        border-top: solid $accent-darken-2;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._eyes: dict[str, str] = {}

    def render(self) -> Text:
        if not self._eyes:
            return Text("")
        text = Text()
        text.append("Eyes: ", style="bold")
        for i, (name, status) in enumerate(sorted(self._eyes.items())):
            if i > 0:
                text.append(" | ")
            text.append(f"{name} ", style="bold")
            if status == "clean":
                text.append("\u2705 clean", style="green")
            elif status == "checking":
                text.append("checking...", style="yellow")
            elif status.startswith("finding"):
                text.append(status, style="red bold")
            elif status == "error":
                text.append("error", style="red")
            else:
                text.append(status, style="dim")
        return text

    def update_eyes(self, statuses: dict[str, str]) -> None:
        self._eyes = dict(statuses)
        self.refresh()

    def set_eye(self, name: str, status: str) -> None:
        self._eyes[name] = status
        self.refresh()


# -- Command Input (Tasks 6-10) ---------------------------------------------


class CommandSubmitted(Message):
    """Posted when user submits a command in command mode."""
    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


class CommandInput(Widget):
    """Bottom input bar for command mode, triggered by ':'."""

    DEFAULT_CSS = """
    CommandInput {
        dock: bottom;
        height: 3;
        display: none;
        padding: 0 1;
        border-top: solid $accent;
    }
    CommandInput.visible {
        display: block;
    }
    CommandInput Input {
        height: 1;
    }
    """

    COMMAND_SUGGESTIONS = [
        "inject", "pause", "resume", "abort",
        "eyes add", "eyes remove", "eyes list",
        "add", "remove",
    ]

    def compose(self) -> ComposeResult:
        yield Static(":", id="cmd-prefix")
        yield Input(placeholder="command...", id="cmd-input")

    def show(self) -> None:
        self.add_class("visible")
        # Schedule focus after the display change takes effect
        self.set_timer(0.05, self._focus_input)

    def _focus_input(self) -> None:
        inp = self.query_one("#cmd-input", Input)
        inp.value = ""
        inp.focus()

    def hide(self) -> None:
        self.remove_class("visible")
        inp = self.query_one("#cmd-input", Input)
        inp.value = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        if command:
            self.post_message(CommandSubmitted(command))
        self.hide()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.hide()
            event.stop()


# -- File List Widget (Task 11) ---------------------------------------------


class FileSelected(Message):
    """Posted when user selects a file for diff view."""
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


class FileListWidget(Widget):
    """Toggleable list of changed files with +/- stats."""

    DEFAULT_CSS = """
    FileListWidget {
        height: auto;
        max-height: 10;
        display: none;
        border: solid $accent;
        padding: 0 1;
    }
    FileListWidget.visible {
        display: block;
    }
    FileListWidget .file-entry {
        height: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._files: list[FileChange] = []
        self._selected = 0

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="file-list-scroll")

    def update_files(self, files: list[FileChange]) -> None:
        self._files = list(files)
        self._rebuild()

    def _rebuild(self) -> None:
        container = self.query_one("#file-list-scroll", VerticalScroll)
        container.remove_children()
        for i, fc in enumerate(self._files):
            marker = {"new": "+", "modified": "~", "deleted": "-", "renamed": "\u2192"}.get(fc.status, "~")
            style = {"new": "green", "modified": "yellow", "deleted": "red"}.get(fc.status, "")
            text = f"  {marker} {fc.path}"
            if fc.lines_added or fc.lines_removed:
                text += f"  +{fc.lines_added}/-{fc.lines_removed}"
            entry = Static(text, classes="file-entry")
            entry._file_index = i
            container.mount(entry)
        self.border_title = f"Files Changed ({len(self._files)})"

    def toggle(self) -> None:
        self.toggle_class("visible")

    def on_click(self, event) -> None:
        # Find which file entry was clicked
        for entry in self.query(".file-entry"):
            idx = getattr(entry, "_file_index", None)
            if idx is not None and idx < len(self._files):
                # Check if click is within this widget's region
                pass
        # Simplified: post file selected for the selected index
        if self._files and self._selected < len(self._files):
            self.post_message(FileSelected(self._files[self._selected].path))

    def on_key(self, event) -> None:
        if event.key == "down" and self._selected < len(self._files) - 1:
            self._selected += 1
            event.stop()
        elif event.key == "up" and self._selected > 0:
            self._selected -= 1
            event.stop()
        elif event.key == "enter" and self._files:
            self.post_message(FileSelected(self._files[self._selected].path))
            event.stop()
        elif event.key == "escape":
            self.toggle_class("visible")
            event.stop()


# -- Diff Overlay (Task 11) -------------------------------------------------


class DiffOverlay(ModalScreen):
    """Modal screen showing a full diff for a selected file."""

    DEFAULT_CSS = """
    DiffOverlay {
        align: center middle;
    }
    DiffOverlay #diff-container {
        width: 90%;
        height: 90%;
        border: solid $accent;
        padding: 1;
    }
    DiffOverlay RichLog {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def __init__(self, filepath: str, diff_text: str) -> None:
        super().__init__()
        self.filepath = filepath
        self.diff_text = diff_text

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-container"):
            yield Static(f"Diff: {self.filepath}", id="diff-title")
            yield RichLog(id="diff-log", highlight=True, wrap=True)

    def on_mount(self) -> None:
        log = self.query_one("#diff-log", RichLog)
        self.query_one("#diff-container").border_title = f"Diff: {self.filepath}"
        if self.diff_text:
            syntax = Syntax(self.diff_text, "diff", theme="monokai", line_numbers=True)
            log.write(syntax)
        else:
            log.write("[dim]No diff available[/dim]")
