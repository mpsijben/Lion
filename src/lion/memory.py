"""Shared JSONL memory for agent communication."""

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, Union


@dataclass
class MemoryEntry:
    """Entry in shared memory for agent communication.

    Standard fields (always present):
        timestamp: When this entry was created
        phase: Pipeline phase (propose, critique, converge, implement, etc.)
        agent: Agent identifier (e.g. "agent_1", "synthesizer")
        type: Entry type (proposal, critique, decision, code, error, etc.)
        content: Main content of the entry

    Context fields (Layer 2, optional):
        reasoning: WHY this approach was chosen
        alternatives: What was considered but rejected
        uncertainties: What the agent is unsure about
        confidence: 0.0-1.0 overall confidence
        belief_state: Rich mode belief tracking (dict)
    """
    timestamp: float
    phase: str          # propose, critique, converge, implement, distill, context, archaeology
    agent: str          # agent identifier (e.g. "agent_1", "synthesizer")
    type: str           # proposal, critique, decision, code, error, compressed_context, shared_context, historical_context
    content: str
    target: Optional[str] = None
    metadata: Optional[dict] = None

    # Layer 2: Context fields
    reasoning: Optional[str] = None
    alternatives: Optional[list[str]] = None
    uncertainties: Optional[list[str]] = None
    confidence: Optional[float] = None
    belief_state: Optional[dict] = None


class SharedMemory:
    """JSONL-based shared memory for agent communication."""

    def __init__(self, run_dir: Union[str, Path], read_only: bool = False):
        self.run_dir = Path(run_dir) if isinstance(run_dir, str) else run_dir
        self.filepath = str(self.run_dir / "memory.jsonl")
        self.read_only = read_only
        if not read_only:
            os.makedirs(run_dir, exist_ok=True)

    @classmethod
    def load(cls, run_dir: Union[str, Path]) -> "SharedMemory":
        """Load existing memory from a completed run (read-only).

        Args:
            run_dir: Path to the run directory containing memory.jsonl

        Returns:
            SharedMemory instance in read-only mode

        Raises:
            FileNotFoundError: If run directory or memory.jsonl doesn't exist
        """
        run_path = Path(run_dir) if isinstance(run_dir, str) else run_dir
        memory_file = run_path / "memory.jsonl"

        if not run_path.exists():
            raise FileNotFoundError(f"Run directory not found: {run_path}")
        if not memory_file.exists():
            raise FileNotFoundError(f"Memory file not found: {memory_file}")

        return cls(run_dir, read_only=True)

    def write(self, entry: MemoryEntry):
        if self.read_only:
            raise RuntimeError("Cannot write to read-only SharedMemory")
        with open(self.filepath, "a") as f:
            data = asdict(entry)
            f.write(json.dumps(data) + "\n")

    def read_all(self) -> list[MemoryEntry]:
        entries = []
        if not os.path.exists(self.filepath):
            return entries
        with open(self.filepath, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    # Handle backwards compatibility: old entries may not have context fields
                    entry = MemoryEntry(
                        timestamp=data.get("timestamp", 0),
                        phase=data.get("phase", ""),
                        agent=data.get("agent", ""),
                        type=data.get("type", ""),
                        content=data.get("content", ""),
                        target=data.get("target"),
                        metadata=data.get("metadata"),
                        reasoning=data.get("reasoning"),
                        alternatives=data.get("alternatives"),
                        uncertainties=data.get("uncertainties"),
                        confidence=data.get("confidence"),
                        belief_state=data.get("belief_state"),
                    )
                    entries.append(entry)
        return entries

    def read_phase(self, phase: str) -> list[MemoryEntry]:
        return [e for e in self.read_all() if e.phase == phase]

    def read_by_type(self, entry_type: str) -> list[MemoryEntry]:
        """Get all entries of a specific type."""
        return [e for e in self.read_all() if e.type == entry_type]

    def get_proposals(self) -> list[MemoryEntry]:
        return self.read_phase("propose")

    def get_critiques(self) -> list[MemoryEntry]:
        return self.read_phase("critique")

    def get_decisions(self) -> list[MemoryEntry]:
        return [e for e in self.read_all() if e.type == "decision"]

    def format_for_prompt(self, entries: list[MemoryEntry]) -> str:
        lines = []
        for e in entries:
            prefix = f"[{e.agent}]"
            if e.target:
                prefix += f" -> [{e.target}]"
            lines.append(f"{prefix}: {e.content}")
        return "\n\n".join(lines)

    def read_by_agent(self, agent: str) -> list[MemoryEntry]:
        """Get all entries from a specific agent."""
        return [e for e in self.read_all() if e.agent == agent]

    def get_agents(self) -> list[str]:
        """Get unique agent identifiers in this memory."""
        agents = []
        seen = set()
        for entry in self.read_all():
            if entry.agent and entry.agent not in seen:
                agents.append(entry.agent)
                seen.add(entry.agent)
        return agents

    def get_phases(self) -> list[str]:
        """Get unique phases in this memory in order of occurrence."""
        phases = []
        seen = set()
        for entry in self.read_all():
            if entry.phase and entry.phase not in seen:
                phases.append(entry.phase)
                seen.add(entry.phase)
        return phases

    def get_entry_by_index(self, index: int) -> Optional[MemoryEntry]:
        """Get a specific entry by its 0-based index."""
        entries = self.read_all()
        if 0 <= index < len(entries):
            return entries[index]
        return None

    def count(self) -> int:
        """Get the total number of entries."""
        return len(self.read_all())
