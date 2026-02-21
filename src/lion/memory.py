"""Shared JSONL memory for agent communication."""

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Optional


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

    def __init__(self, run_dir: str):
        self.filepath = os.path.join(run_dir, "memory.jsonl")
        os.makedirs(run_dir, exist_ok=True)

    def write(self, entry: MemoryEntry):
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
