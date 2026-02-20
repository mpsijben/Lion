"""Shared JSONL memory for agent communication."""

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class MemoryEntry:
    timestamp: float
    phase: str          # propose, critique, converge, implement
    agent: str          # agent identifier (e.g. "agent_1", "synthesizer")
    type: str           # proposal, critique, decision, code, error
    content: str
    target: Optional[str] = None
    metadata: Optional[dict] = None


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
                    entries.append(MemoryEntry(**json.loads(line)))
        return entries

    def read_phase(self, phase: str) -> list[MemoryEntry]:
        return [e for e in self.read_all() if e.phase == phase]

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
