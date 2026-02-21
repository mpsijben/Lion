"""View rendering for LionCLI inspection commands.

Provides ViewRenderer class for displaying Layer 2 reasoning data
(reasoning, alternatives, uncertainties, confidence) in full detail,
separate from the Display class used for streaming output.
"""

import shutil
from datetime import datetime
from typing import Optional

from ..display import GREEN, YELLOW, RED, BLUE, CYAN, DIM, BOLD, RESET, MAGENTA
from ..memory import MemoryEntry


def get_terminal_width(fallback: int = 80) -> int:
    """Get current terminal width with fallback.

    Args:
        fallback: Default width if detection fails

    Returns:
        Terminal width in characters
    """
    try:
        size = shutil.get_terminal_size(fallback=(fallback, 24))
        return size.columns
    except Exception:
        return fallback


class ViewRenderer:
    """Renders memory entries for inspection display.

    Unlike Display which handles streaming output during execution,
    ViewRenderer shows full Layer 2 fields without truncation for
    post-execution inspection.
    """

    @staticmethod
    def render_step_summary(
        entry: MemoryEntry, index: int, collapsed: bool = True
    ) -> str:
        """Render a brief one-line summary of a memory entry.

        Args:
            entry: The memory entry to render
            index: The entry's index (for reference)
            collapsed: If True, show [+N] indicator for expandable content

        Returns:
            Formatted summary string
        """
        timestamp = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
        confidence_str = ""
        if entry.confidence is not None:
            conf_pct = int(entry.confidence * 100)
            if conf_pct >= 80:
                conf_color = GREEN
            elif conf_pct >= 50:
                conf_color = YELLOW
            else:
                conf_color = RED
            confidence_str = f" {conf_color}[{conf_pct}%]{RESET}"

        # Truncate content for summary
        content_preview = entry.content.replace("\n", " ")[:80]
        has_more_content = len(entry.content) > 80
        has_layer2 = bool(
            entry.reasoning or entry.alternatives or entry.uncertainties
        )

        # Build collapse indicator
        if collapsed and (has_more_content or has_layer2):
            collapse_indicator = f" {CYAN}[+{index}]{RESET}"
            if has_more_content:
                content_preview += "..."
        elif not collapsed:
            collapse_indicator = f" {DIM}[-{index}]{RESET}"
            if has_more_content:
                content_preview += "..."
        else:
            collapse_indicator = ""
            if has_more_content:
                content_preview += "..."

        return (
            f"{DIM}[{index}]{RESET} {timestamp} "
            f"{CYAN}{entry.phase}{RESET} "
            f"{BLUE}{entry.agent}{RESET} "
            f"({entry.type}){confidence_str}: "
            f"{DIM}{content_preview}{RESET}{collapse_indicator}"
        )

    @staticmethod
    def render_step_detail(entry: MemoryEntry, index: int) -> str:
        """Render full details of a memory entry.

        Shows all fields including Layer 2 context without truncation.

        Args:
            entry: The memory entry to render
            index: The entry's index

        Returns:
            Formatted detail string
        """
        lines = []

        # Header
        timestamp = datetime.fromtimestamp(entry.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"\n{BOLD}=== Entry {index} ==={RESET}")
        lines.append(f"{DIM}Timestamp:{RESET} {timestamp}")
        lines.append(f"{DIM}Phase:{RESET}     {CYAN}{entry.phase}{RESET}")
        lines.append(f"{DIM}Agent:{RESET}     {BLUE}{entry.agent}{RESET}")
        lines.append(f"{DIM}Type:{RESET}      {entry.type}")

        if entry.target:
            lines.append(f"{DIM}Target:{RESET}    {entry.target}")

        # Confidence
        if entry.confidence is not None:
            conf_pct = int(entry.confidence * 100)
            if conf_pct >= 80:
                conf_color = GREEN
            elif conf_pct >= 50:
                conf_color = YELLOW
            else:
                conf_color = RED
            lines.append(f"{DIM}Confidence:{RESET} {conf_color}{conf_pct}%{RESET}")

        # Content (full, not truncated)
        lines.append(f"\n{BOLD}Content:{RESET}")
        for line in entry.content.split("\n"):
            lines.append(f"  {line}")

        # Layer 2 fields
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

        if entry.belief_state:
            lines.append(f"\n{BOLD}{BLUE}Belief State:{RESET}")
            for key, value in entry.belief_state.items():
                lines.append(f"  {key}: {value}")

        if entry.metadata:
            lines.append(f"\n{DIM}Metadata:{RESET}")
            for key, value in entry.metadata.items():
                lines.append(f"  {DIM}{key}: {value}{RESET}")

        return "\n".join(lines)

    @staticmethod
    def render_entry(
        entry: MemoryEntry, index: int, collapsed: bool = True
    ) -> str:
        """Render an entry based on collapse state.

        Args:
            entry: The memory entry to render
            index: The entry's index
            collapsed: If True, show summary; if False, show full details

        Returns:
            Formatted entry string
        """
        if collapsed:
            return ViewRenderer.render_step_summary(entry, index, collapsed=True)
        else:
            return ViewRenderer.render_step_detail(entry, index)

    @staticmethod
    def render_expand_hint(collapsed_count: int, total: int) -> str:
        """Render a footer hint about expanding entries.

        Args:
            collapsed_count: Number of collapsed entries
            total: Total number of entries

        Returns:
            Formatted hint string, or empty string if nothing collapsed
        """
        if collapsed_count == 0:
            return f"{DIM}All entries expanded. Use :collapse-all to collapse.{RESET}"
        elif collapsed_count == total:
            return f"{DIM}Type :expand <n> to see full content, or :expand-all for all.{RESET}"
        else:
            expanded = total - collapsed_count
            return (
                f"{DIM}{expanded}/{total} expanded. "
                f"Use :expand <n> or :collapse <n> to toggle.{RESET}"
            )

    @staticmethod
    def render_reasoning(entry: MemoryEntry) -> str:
        """Render only the reasoning field.

        Args:
            entry: The memory entry

        Returns:
            Formatted reasoning or indication of none
        """
        if not entry.reasoning:
            return f"{DIM}No reasoning recorded for this entry.{RESET}"

        lines = [f"{BOLD}{MAGENTA}Reasoning ({entry.agent}):{RESET}"]
        for line in entry.reasoning.split("\n"):
            lines.append(f"  {line}")
        return "\n".join(lines)

    @staticmethod
    def render_alternatives(entry: MemoryEntry) -> str:
        """Render only the alternatives field.

        Args:
            entry: The memory entry

        Returns:
            Formatted alternatives or indication of none
        """
        if not entry.alternatives:
            return f"{DIM}No alternatives recorded for this entry.{RESET}"

        lines = [f"{BOLD}{YELLOW}Alternatives Considered ({entry.agent}):{RESET}"]
        for i, alt in enumerate(entry.alternatives, 1):
            lines.append(f"  {i}. {alt}")
        return "\n".join(lines)

    @staticmethod
    def render_uncertainties(entry: MemoryEntry) -> str:
        """Render only the uncertainties field.

        Args:
            entry: The memory entry

        Returns:
            Formatted uncertainties or indication of none
        """
        if not entry.uncertainties:
            return f"{DIM}No uncertainties recorded for this entry.{RESET}"

        lines = [f"{BOLD}{RED}Uncertainties ({entry.agent}):{RESET}"]
        for unc in entry.uncertainties:
            lines.append(f"  ? {unc}")
        return "\n".join(lines)

    @staticmethod
    def render_confidence(entry: MemoryEntry) -> str:
        """Render confidence score with visual indicator.

        Args:
            entry: The memory entry

        Returns:
            Formatted confidence display
        """
        if entry.confidence is None:
            return f"{DIM}No confidence score recorded for this entry.{RESET}"

        # Clamp confidence to valid range (0-100%)
        conf_pct = max(0, min(100, int(entry.confidence * 100)))
        if conf_pct >= 80:
            conf_color = GREEN
            indicator = "HIGH"
        elif conf_pct >= 50:
            conf_color = YELLOW
            indicator = "MEDIUM"
        else:
            conf_color = RED
            indicator = "LOW"

        # Visual bar (20 chars total)
        filled = conf_pct // 5
        bar = "█" * filled + "░" * (20 - filled)

        return (
            f"{BOLD}Confidence ({entry.agent}):{RESET}\n"
            f"  {conf_color}{bar} {conf_pct}% ({indicator}){RESET}"
        )

    @staticmethod
    def render_context_short(entry_count: int, total_chars: int, has_run: bool) -> str:
        """Return condensed one-line context summary.

        Args:
            entry_count: Number of memory entries
            total_chars: Total character count of all entry content
            has_run: Whether a run is currently loaded

        Returns:
            Formatted one-line summary like "Context: 5 entries, 2.3k tokens"
        """
        if not has_run:
            return "Context: no run loaded"
        if entry_count == 0:
            return "Context: empty"

        # Approximate tokens as chars // 4 (standard heuristic)
        tokens = total_chars // 4
        if tokens >= 1000:
            token_str = f"{tokens / 1000:.1f}k"
        else:
            token_str = str(tokens)

        return f"Context: {entry_count} entries, {token_str} tokens"

    @staticmethod
    def render_context_minimal(entries: list[MemoryEntry]) -> str:
        """Render minimal context: token count only.

        Args:
            entries: List of memory entries

        Returns:
            Formatted string like "Context: 2.3k tokens"
        """
        if not entries:
            return "Context: 0 tokens"

        total_chars = sum(len(e.content) for e in entries)
        tokens = total_chars // 4

        if tokens >= 1000:
            token_str = f"{tokens / 1000:.1f}k"
        else:
            token_str = str(tokens)

        return f"Context: {token_str} tokens"

    @staticmethod
    def render_context_normal(entries: list[MemoryEntry]) -> str:
        """Render normal context: entry names + token counts per entry.

        Args:
            entries: List of memory entries

        Returns:
            Formatted string with per-entry token counts
        """
        if not entries:
            return "Context: empty"

        lines = []
        total_tokens = 0

        # Group entries by agent/phase for cleaner display
        for i, entry in enumerate(entries):
            chars = len(entry.content)
            tokens = chars // 4
            total_tokens += tokens

            if tokens >= 1000:
                token_str = f"{tokens / 1000:.1f}k"
            else:
                token_str = str(tokens)

            # Show agent/phase with token count
            lines.append(
                f"  {DIM}[{i}]{RESET} {CYAN}{entry.phase}{RESET} "
                f"{BLUE}{entry.agent}{RESET} ({entry.type}): {token_str} tokens"
            )

        # Total summary
        if total_tokens >= 1000:
            total_str = f"{total_tokens / 1000:.1f}k"
        else:
            total_str = str(total_tokens)

        header = f"{BOLD}Context:{RESET} {len(entries)} entries, {total_str} tokens total"
        lines.insert(0, header)

        return "\n".join(lines)

    @staticmethod
    def render_context_full(entries: list[MemoryEntry]) -> str:
        """Render full context: entries with content preview.

        Args:
            entries: List of memory entries

        Returns:
            Formatted string with content preview (first 100 chars)
        """
        if not entries:
            return "Context: empty"

        lines = []
        total_tokens = 0

        for i, entry in enumerate(entries):
            chars = len(entry.content)
            tokens = chars // 4
            total_tokens += tokens

            if tokens >= 1000:
                token_str = f"{tokens / 1000:.1f}k"
            else:
                token_str = str(tokens)

            # Entry header
            lines.append(
                f"  {DIM}[{i}]{RESET} {CYAN}{entry.phase}{RESET} "
                f"{BLUE}{entry.agent}{RESET} ({entry.type}): {token_str} tokens"
            )

            # Content preview (first 100 chars)
            preview = entry.content.replace("\n", " ")[:100]
            if len(entry.content) > 100:
                preview += "..."
            lines.append(f"      {DIM}{preview}{RESET}")

            # Layer 2 indicators
            layer2_parts = []
            if entry.reasoning:
                layer2_parts.append(f"{MAGENTA}reasoning{RESET}")
            if entry.alternatives:
                layer2_parts.append(f"{YELLOW}alternatives({len(entry.alternatives)}){RESET}")
            if entry.uncertainties:
                layer2_parts.append(f"{RED}uncertainties({len(entry.uncertainties)}){RESET}")
            if entry.confidence is not None:
                conf_pct = int(entry.confidence * 100)
                if conf_pct >= 80:
                    conf_color = GREEN
                elif conf_pct >= 50:
                    conf_color = YELLOW
                else:
                    conf_color = RED
                layer2_parts.append(f"{conf_color}confidence({conf_pct}%){RESET}")

            if layer2_parts:
                lines.append(f"      Layer 2: {', '.join(layer2_parts)}")

        # Total summary
        if total_tokens >= 1000:
            total_str = f"{total_tokens / 1000:.1f}k"
        else:
            total_str = str(total_tokens)

        header = f"{BOLD}Context:{RESET} {len(entries)} entries, {total_str} tokens total"
        lines.insert(0, header)

        return "\n".join(lines)

    @staticmethod
    def render_context_at_level(entries: list[MemoryEntry], level: str) -> str:
        """Render context based on verbosity level.

        Args:
            entries: List of memory entries
            level: Verbosity level ("minimal", "normal", "full")

        Returns:
            Formatted context string at the specified verbosity level
        """
        match level:
            case "minimal":
                return ViewRenderer.render_context_minimal(entries)
            case "normal":
                return ViewRenderer.render_context_normal(entries)
            case "full":
                return ViewRenderer.render_context_full(entries)
            case _:
                return ViewRenderer.render_context_normal(entries)  # fallback

    @staticmethod
    def render_status_line(session) -> str:
        """Render a one-line status showing current context state.

        Format: [context: full | 12 entries | 8 collapsed]

        When interactive mode is active, also shows keyboard shortcuts.

        Args:
            session: SessionState object

        Returns:
            Formatted status line string
        """
        # Get entry count and collapsed count
        if session.has_run() and session.memory:
            entries = session.memory.read_all()
            total = len(entries)
            collapsed = session.get_collapsed_count()
        else:
            total = 0
            collapsed = 0

        # Build status parts
        parts = []
        parts.append(f"context: {session.context_level}")
        parts.append(f"{total} entries")
        if total > 0:
            parts.append(f"{collapsed} collapsed")

        status = " | ".join(parts)

        # Add shortcut hints based on interactive mode
        if session.interactive_mode:
            hints = f"{DIM}[Ctrl+L: verbosity | Ctrl+T: toggle]{RESET}"
            return f"{hints} [{status}]"
        else:
            hints = f"{DIM}[:cv verbosity | :ct toggle]{RESET}"
            return f"{hints} [{status}]"

    @staticmethod
    def render_run_summary(
        run_id: str,
        entries: list[MemoryEntry],
        phases: list[str],
        agents: list[str],
    ) -> str:
        """Render a summary of a loaded run.

        Args:
            run_id: The run's directory name
            entries: All memory entries
            phases: Unique phases in order
            agents: Unique agents

        Returns:
            Formatted run summary
        """
        lines = [
            f"\n{BOLD}Run: {run_id}{RESET}",
            f"{DIM}{'=' * 50}{RESET}",
        ]

        # Stats
        lines.append(f"Entries: {len(entries)}")
        lines.append(f"Phases:  {', '.join(phases)}")
        lines.append(f"Agents:  {', '.join(agents)}")

        # Count entries with Layer 2 data
        with_reasoning = sum(1 for e in entries if e.reasoning)
        with_alternatives = sum(1 for e in entries if e.alternatives)
        with_uncertainties = sum(1 for e in entries if e.uncertainties)
        with_confidence = sum(1 for e in entries if e.confidence is not None)

        lines.append(f"\n{BOLD}Layer 2 Data:{RESET}")
        lines.append(f"  Reasoning:     {with_reasoning}/{len(entries)} entries")
        lines.append(f"  Alternatives:  {with_alternatives}/{len(entries)} entries")
        lines.append(f"  Uncertainties: {with_uncertainties}/{len(entries)} entries")
        lines.append(f"  Confidence:    {with_confidence}/{len(entries)} entries")

        # Time range
        if entries:
            start = datetime.fromtimestamp(entries[0].timestamp)
            end = datetime.fromtimestamp(entries[-1].timestamp)
            duration = (end - start).total_seconds()
            lines.append(f"\n{DIM}Duration: {duration:.1f}s{RESET}")

        return "\n".join(lines)
