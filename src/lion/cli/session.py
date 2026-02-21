"""Session state management for LionCLI.

Manages interactive session context including current run directory,
loaded memory, command history, view mode, and configuration.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Literal

from ..memory import SharedMemory


@dataclass
class SessionState:
    """State maintained across REPL commands.

    Attributes:
        run_dir: Current run directory being inspected
        memory: Loaded SharedMemory for the current run
        history: List of executed commands/prompts
        debug_mode: Whether to show full tracebacks
        view_mode: Current display detail level
        reason_mode: Current reasoning visibility mode
        config: Loaded Lion configuration
        config_path: Path to the loaded config file
        current_lens: Currently active lens for next execution
        collapsed_entries: Set of entry indices that are collapsed (summary view)
        expand_mode: Default expand behavior for new entries
        prompt_style: Prompt display style (default or enriched)
        context_level: Context display verbosity (minimal, normal, full)
    """

    run_dir: Optional[Path] = None
    memory: Optional[SharedMemory] = None
    history: list[str] = field(default_factory=list)
    debug_mode: bool = False
    view_mode: Literal["summary", "detail"] = "summary"
    reason_mode: Literal["off", "on", "full"] = "off"
    config: dict = field(default_factory=dict)
    config_path: Optional[Path] = None
    current_lens: Optional[str] = None
    cwd: Path = field(default_factory=Path.cwd)
    # Collapse/expand state for entries (ephemeral UI state, not persisted)
    collapsed_entries: set[int] = field(default_factory=set)
    expand_mode: Literal["all", "none", "selective"] = "none"
    prompt_style: Literal["default", "enriched"] = "default"
    # Context display verbosity level
    context_level: Literal["minimal", "normal", "full"] = "normal"
    # Interactive mode for keyboard shortcuts (Ctrl+L, Ctrl+T)
    interactive_mode: bool = False

    def load_run(self, run_dir: Path) -> bool:
        """Load a run directory for inspection.

        Args:
            run_dir: Path to the run directory

        Returns:
            True if loaded successfully, False otherwise
        """
        if not run_dir.exists():
            return False

        memory_file = run_dir / "memory.jsonl"
        if not memory_file.exists():
            return False

        self.run_dir = run_dir
        self.memory = SharedMemory.load(run_dir)
        return True

    def clear_run(self):
        """Clear the current run from session."""
        self.run_dir = None
        self.memory = None

    def has_run(self) -> bool:
        """Check if a run is currently loaded."""
        return self.run_dir is not None and self.memory is not None

    def get_run_id(self) -> Optional[str]:
        """Get the current run's ID (directory name)."""
        if self.run_dir:
            return self.run_dir.name
        return None

    def is_collapsed(self, index: int) -> bool:
        """Check if an entry is collapsed.

        Args:
            index: The entry index

        Returns:
            True if entry is collapsed (showing summary), False if expanded
        """
        if self.expand_mode == "all":
            # In "all" mode, everything expanded unless explicitly collapsed
            return index in self.collapsed_entries
        elif self.expand_mode == "none":
            # In "none" mode, everything collapsed by default
            return True
        else:  # selective
            # In selective mode, collapsed_entries tracks which are collapsed
            return index in self.collapsed_entries

    def expand_entry(self, index: int) -> None:
        """Expand an entry (show full detail).

        Args:
            index: The entry index to expand
        """
        if self.expand_mode == "all":
            # Remove from collapsed set
            self.collapsed_entries.discard(index)
        elif self.expand_mode == "none":
            # Switch to selective mode and mark all as collapsed except this one
            if self.has_run() and self.memory:
                total = self.memory.count()
                self.collapsed_entries = set(range(total))
                self.collapsed_entries.discard(index)
            self.expand_mode = "selective"
        else:  # selective
            # Remove from collapsed set
            self.collapsed_entries.discard(index)

    def collapse_entry(self, index: int) -> None:
        """Collapse an entry (show summary only).

        Args:
            index: The entry index to collapse
        """
        if self.expand_mode == "none":
            pass  # Already collapsed by default
        else:
            self.collapsed_entries.add(index)
            self.expand_mode = "selective"

    def expand_all(self) -> None:
        """Expand all entries."""
        self.expand_mode = "all"
        self.collapsed_entries.clear()

    def collapse_all(self) -> None:
        """Collapse all entries."""
        self.expand_mode = "none"
        self.collapsed_entries.clear()

    def get_collapsed_count(self) -> int:
        """Get the count of collapsed entries.

        Returns:
            Number of collapsed entries based on current mode
        """
        if not self.has_run() or not self.memory:
            return 0

        total = self.memory.count()
        if self.expand_mode == "all":
            return len(self.collapsed_entries)
        elif self.expand_mode == "none":
            return total
        else:  # selective
            # In selective mode, entries NOT in collapsed_entries are expanded
            expanded_count = len([i for i in range(total) if i not in self.collapsed_entries])
            return total - expanded_count

    def cycle_context_verbosity(self) -> str:
        """Cycle through context verbosity levels.

        Rotates: minimal → normal → full → minimal

        Returns:
            The new verbosity level
        """
        cycle = {"minimal": "normal", "normal": "full", "full": "minimal"}
        self.context_level = cycle.get(self.context_level, "normal")
        return self.context_level

    def toggle_expand_collapse_all(self) -> str:
        """Toggle between expand-all and collapse-all states.

        If any entries are collapsed, expand all.
        Otherwise, collapse all.

        Returns:
            Description of the action taken
        """
        if self.expand_mode == "all" and not self.collapsed_entries:
            # All expanded, so collapse all
            self.collapse_all()
            return "collapsed"
        else:
            # Some or all collapsed, so expand all
            self.expand_all()
            return "expanded"
