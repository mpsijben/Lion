"""Rich library integration for enhanced context display.

Provides collapsible/expandable panels for memory entries using the rich library.
Falls back gracefully when rich is not installed.
"""

import shutil
from datetime import datetime
from typing import Optional, TYPE_CHECKING

# Graceful import handling - rich is an optional dependency
try:
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Console
    from rich.style import Style
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Panel = None
    Text = None
    Console = None
    Style = None
    box = None

if TYPE_CHECKING:
    from ..memory import MemoryEntry


def get_terminal_width() -> int:
    """Get current terminal width with fallback.

    Returns:
        Terminal width in characters, defaults to 80 if detection fails.
    """
    try:
        size = shutil.get_terminal_size(fallback=(80, 24))
        return size.columns
    except Exception:
        return 80


class RichContextPanel:
    """Renders memory entries as Rich panels with collapse/expand indicators.

    Provides enhanced visual rendering when rich is available, with
    automatic fallback to plain text when it's not.
    """

    def __init__(self):
        """Initialize the panel renderer."""
        self._console = Console() if RICH_AVAILABLE else None

    @staticmethod
    def is_available() -> bool:
        """Check if Rich rendering is available.

        Returns:
            True if rich library is installed and usable.
        """
        return RICH_AVAILABLE

    def render_collapsed_indicator(self, index: int) -> str:
        """Render a styled collapsed indicator [+N].

        Args:
            index: The entry index

        Returns:
            Styled indicator string (with ANSI codes if rich available)
        """
        if RICH_AVAILABLE:
            # Use rich Text for styled output
            text = Text()
            text.append(f"[+{index}]", style="cyan bold")
            # Convert to string with ANSI codes
            return str(self._render_to_string(text))
        else:
            # Plain ANSI fallback
            return f"\033[36m\033[1m[+{index}]\033[0m"

    def render_expanded_indicator(self, index: int) -> str:
        """Render a styled expanded indicator [-N].

        Args:
            index: The entry index

        Returns:
            Styled indicator string
        """
        if RICH_AVAILABLE:
            text = Text()
            text.append(f"[-{index}]", style="dim")
            return str(self._render_to_string(text))
        else:
            return f"\033[2m[-{index}]\033[0m"

    def _render_to_string(self, renderable) -> str:
        """Render a rich object to a string with ANSI codes.

        Args:
            renderable: Any Rich renderable object

        Returns:
            String representation with ANSI codes
        """
        if not RICH_AVAILABLE or not self._console:
            return str(renderable)

        from io import StringIO
        string_io = StringIO()
        temp_console = Console(file=string_io, force_terminal=True, width=get_terminal_width())
        temp_console.print(renderable, end="")
        return string_io.getvalue()

    def render_entry_panel(
        self,
        entry: "MemoryEntry",
        index: int,
        collapsed: bool = True,
        terminal_width: Optional[int] = None
    ) -> str:
        """Render a memory entry as a Rich panel.

        Args:
            entry: The memory entry to render
            index: The entry's index
            collapsed: If True, show summary; if False, show full details
            terminal_width: Optional terminal width (auto-detected if None)

        Returns:
            Formatted panel string
        """
        if not RICH_AVAILABLE:
            # Fallback to plain text
            return self._render_plain_entry(entry, index, collapsed)

        width = terminal_width or get_terminal_width()
        # Ensure panel fits within terminal, leave margin for borders
        panel_width = min(width - 4, 100)

        if collapsed:
            return self._render_collapsed_panel(entry, index, panel_width)
        else:
            return self._render_expanded_panel(entry, index, panel_width)

    def _render_collapsed_panel(
        self,
        entry: "MemoryEntry",
        index: int,
        width: int
    ) -> str:
        """Render a collapsed entry panel.

        Args:
            entry: The memory entry
            index: Entry index
            width: Panel width

        Returns:
            Formatted collapsed panel string
        """
        # Build header with indicator
        timestamp = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")

        # Create rich Text for content
        content = Text()
        content.append(f"[+{index}]", style="cyan bold")
        content.append(" ")

        # Truncate content for summary
        content_preview = entry.content.replace("\n", " ")
        max_content_len = width - 40  # Leave room for metadata
        if len(content_preview) > max_content_len:
            content_preview = content_preview[:max_content_len] + "..."

        content.append(content_preview, style="dim")

        # Add confidence if present
        if entry.confidence is not None:
            conf_pct = int(entry.confidence * 100)
            if conf_pct >= 80:
                conf_style = "green"
            elif conf_pct >= 50:
                conf_style = "yellow"
            else:
                conf_style = "red"
            content.append(f" [{conf_pct}%]", style=conf_style)

        # Check for Layer 2 data
        has_layer2 = bool(entry.reasoning or entry.alternatives or entry.uncertainties)
        if has_layer2:
            content.append(" ", style="dim")
            if entry.reasoning:
                content.append("R", style="magenta")
            if entry.alternatives:
                content.append("A", style="yellow")
            if entry.uncertainties:
                content.append("U", style="red")

        # Create panel
        title = f"Entry {index} - {timestamp} - {entry.phase}"
        panel = Panel(
            content,
            title=title,
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            width=width,
            padding=(0, 1),
        )

        return self._render_to_string(panel)

    def _render_expanded_panel(
        self,
        entry: "MemoryEntry",
        index: int,
        width: int
    ) -> str:
        """Render an expanded entry panel with full details.

        Args:
            entry: The memory entry
            index: Entry index
            width: Panel width

        Returns:
            Formatted expanded panel string
        """
        timestamp = datetime.fromtimestamp(entry.timestamp).strftime("%Y-%m-%d %H:%M:%S")

        # Build full content
        content = Text()
        content.append(f"[-{index}]", style="dim")
        content.append(" ")
        content.append(entry.agent, style="blue bold")
        content.append(f" ({entry.type})", style="dim")

        if entry.target:
            content.append(f" -> {entry.target}", style="dim")

        # Confidence bar
        if entry.confidence is not None:
            conf_pct = int(entry.confidence * 100)
            if conf_pct >= 80:
                conf_style = "green"
                indicator = "HIGH"
            elif conf_pct >= 50:
                conf_style = "yellow"
                indicator = "MEDIUM"
            else:
                conf_style = "red"
                indicator = "LOW"
            content.append("\n")
            filled = conf_pct // 5
            bar = "\u2588" * filled + "\u2591" * (20 - filled)
            content.append(f"  {bar} {conf_pct}% ({indicator})", style=conf_style)

        content.append("\n\n")

        # Full content
        content.append("Content:\n", style="bold")
        for line in entry.content.split("\n"):
            content.append(f"  {line}\n")

        # Layer 2 fields
        if entry.reasoning:
            content.append("\n")
            content.append("Reasoning:\n", style="bold magenta")
            for line in entry.reasoning.split("\n"):
                content.append(f"  {line}\n")

        if entry.alternatives:
            content.append("\n")
            content.append("Alternatives Considered:\n", style="bold yellow")
            for alt in entry.alternatives:
                content.append(f"  - {alt}\n")

        if entry.uncertainties:
            content.append("\n")
            content.append("Uncertainties:\n", style="bold red")
            for unc in entry.uncertainties:
                content.append(f"  ? {unc}\n")

        if entry.belief_state:
            content.append("\n")
            content.append("Belief State:\n", style="bold blue")
            for key, value in entry.belief_state.items():
                content.append(f"  {key}: {value}\n")

        # Create panel
        title = f"Entry {index} - {timestamp} - {entry.phase}"
        panel = Panel(
            content,
            title=title,
            title_align="left",
            border_style="green",
            box=box.ROUNDED,
            width=width,
            padding=(0, 1),
        )

        return self._render_to_string(panel)

    def _render_plain_entry(
        self,
        entry: "MemoryEntry",
        index: int,
        collapsed: bool
    ) -> str:
        """Fallback plain text rendering when rich is not available.

        Args:
            entry: The memory entry
            index: Entry index
            collapsed: Whether to show collapsed view

        Returns:
            Plain text formatted entry
        """
        # Import ANSI codes from display
        from ..display import GREEN, YELLOW, RED, BLUE, CYAN, DIM, BOLD, RESET
        MAGENTA = "\033[35m"

        timestamp = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")

        if collapsed:
            # Summary view
            content_preview = entry.content.replace("\n", " ")[:80]
            has_more = len(entry.content) > 80
            has_layer2 = bool(entry.reasoning or entry.alternatives or entry.uncertainties)

            indicator = f"{CYAN}[+{index}]{RESET}" if (has_more or has_layer2) else ""
            preview_text = content_preview + ("..." if has_more else "")

            return (
                f"{DIM}[{index}]{RESET} {timestamp} "
                f"{CYAN}{entry.phase}{RESET} "
                f"{BLUE}{entry.agent}{RESET} "
                f"({entry.type}): "
                f"{DIM}{preview_text}{RESET} {indicator}"
            )
        else:
            # Full detail view
            lines = []
            lines.append(f"\n{BOLD}=== Entry {index} ==={RESET}")
            lines.append(f"{DIM}Timestamp:{RESET} {timestamp}")
            lines.append(f"{DIM}Phase:{RESET}     {CYAN}{entry.phase}{RESET}")
            lines.append(f"{DIM}Agent:{RESET}     {BLUE}{entry.agent}{RESET}")
            lines.append(f"{DIM}Type:{RESET}      {entry.type}")

            if entry.target:
                lines.append(f"{DIM}Target:{RESET}    {entry.target}")

            if entry.confidence is not None:
                conf_pct = int(entry.confidence * 100)
                if conf_pct >= 80:
                    conf_color = GREEN
                elif conf_pct >= 50:
                    conf_color = YELLOW
                else:
                    conf_color = RED
                lines.append(f"{DIM}Confidence:{RESET} {conf_color}{conf_pct}%{RESET}")

            lines.append(f"\n{BOLD}Content:{RESET}")
            for line in entry.content.split("\n"):
                lines.append(f"  {line}")

            if entry.reasoning:
                lines.append(f"\n{BOLD}{MAGENTA}Reasoning:{RESET}")
                for line in entry.reasoning.split("\n"):
                    lines.append(f"  {line}")

            if entry.alternatives:
                lines.append(f"\n{BOLD}{YELLOW}Alternatives Considered:{RESET}")
                for alt in entry.alternatives:
                    lines.append(f"  - {alt}")

            if entry.uncertainties:
                lines.append(f"\n{BOLD}{RED}Uncertainties:{RESET}")
                for unc in entry.uncertainties:
                    lines.append(f"  ? {unc}")

            return "\n".join(lines)

    def render_footer_hint(
        self,
        collapsed_count: int,
        total: int,
        terminal_width: Optional[int] = None
    ) -> str:
        """Render an actionable footer hint about expand/collapse commands.

        Args:
            collapsed_count: Number of collapsed entries
            total: Total number of entries
            terminal_width: Optional terminal width

        Returns:
            Formatted hint string
        """
        if not RICH_AVAILABLE:
            # Plain text fallback
            from ..display import DIM, CYAN, RESET
            if collapsed_count == 0:
                return f"{DIM}All entries expanded. Use :collapse-all to collapse.{RESET}"
            elif collapsed_count == total:
                return f"{DIM}Tip: Type {CYAN}:expand N{RESET}{DIM} or {CYAN}:e N{RESET}{DIM} to expand entry N{RESET}"
            else:
                expanded = total - collapsed_count
                return (
                    f"{DIM}{expanded}/{total} expanded. "
                    f"Use {CYAN}:expand N{RESET}{DIM} or {CYAN}:collapse N{RESET}{DIM} to toggle.{RESET}"
                )

        width = terminal_width or get_terminal_width()

        # Create styled hint
        text = Text()

        if collapsed_count == 0:
            text.append("All entries expanded. ", style="dim")
            text.append("Use ", style="dim")
            text.append(":collapse-all", style="cyan")
            text.append(" to collapse.", style="dim")
        elif collapsed_count == total:
            text.append("Tip: ", style="dim")
            text.append("Type ", style="dim")
            text.append(":expand N", style="cyan bold")
            text.append(" or ", style="dim")
            text.append(":e N", style="cyan bold")
            text.append(" to expand entry N", style="dim")
        else:
            expanded = total - collapsed_count
            text.append(f"{expanded}/{total} expanded. ", style="dim")
            text.append("Use ", style="dim")
            text.append(":expand N", style="cyan")
            text.append(" or ", style="dim")
            text.append(":collapse N", style="cyan")
            text.append(" to toggle.", style="dim")

        return self._render_to_string(text)


# Module-level singleton for convenience
_panel_renderer: Optional[RichContextPanel] = None


def get_panel_renderer() -> RichContextPanel:
    """Get the singleton panel renderer instance.

    Returns:
        The shared RichContextPanel instance
    """
    global _panel_renderer
    if _panel_renderer is None:
        _panel_renderer = RichContextPanel()
    return _panel_renderer
