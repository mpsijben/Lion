"""Data structures for Layer 2 Context Ecosystem."""

from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class ContextMode(Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    RICH = "rich"
    AUTO = "auto"


@dataclass
class BeliefState:
    """Rich mode only: what an agent knows and believes."""
    knows: list[str] = field(default_factory=list)
    believes: list[str] = field(default_factory=list)
    others_likely_missing: list[str] = field(default_factory=list)


@dataclass
class ContextPackage:
    """Structured context produced by every agent alongside their output."""

    # Always present (minimal mode)
    output: str                          # The actual response/proposal/code
    agent_id: str                        # Which agent produced this
    model: str                           # Which LLM (claude, gemini, etc.)

    # Standard mode additions (~200-400 extra tokens)
    reasoning: Optional[str] = None      # WHY this approach was chosen
    alternatives: list[str] = field(default_factory=list)
                                         # What was considered but rejected (with reason)
    uncertainties: list[str] = field(default_factory=list)
                                         # What the agent is unsure about
    confidence: Optional[float] = None   # 0.0-1.0 overall confidence

    # Rich mode additions (~400-600 extra tokens on top of standard)
    assumptions: list[str] = field(default_factory=list)
                                         # What the agent assumes to be true
    risks: list[str] = field(default_factory=list)
                                         # Identified risks
    dependencies: list[str] = field(default_factory=list)
                                         # External dependencies being relied on
    files_examined: list[str] = field(default_factory=list)
                                         # Which files were read
    questions_for_team: list[str] = field(default_factory=list)
                                         # Questions this agent has for others
    belief_state: Optional[BeliefState] = None
                                         # Rich mode belief tracking

    def to_shared_memory(self) -> dict:
        """Serialize for JSONL storage."""
        data = {
            "output": self.output,
            "agent_id": self.agent_id,
            "model": self.model,
        }
        if self.reasoning:
            data["reasoning"] = self.reasoning
        if self.alternatives:
            data["alternatives"] = self.alternatives
        if self.uncertainties:
            data["uncertainties"] = self.uncertainties
        if self.confidence is not None:
            data["confidence"] = self.confidence
        if self.assumptions:
            data["assumptions"] = self.assumptions
        if self.risks:
            data["risks"] = self.risks
        if self.dependencies:
            data["dependencies"] = self.dependencies
        if self.files_examined:
            data["files_examined"] = self.files_examined
        if self.questions_for_team:
            data["questions_for_team"] = self.questions_for_team
        if self.belief_state:
            data["belief_state"] = asdict(self.belief_state)
        return data

    def token_estimate(self) -> int:
        """Rough token estimate for this package's metadata (excluding output)."""
        tokens = 0
        if self.reasoning:
            tokens += len(self.reasoning.split()) * 1.3
        tokens += sum(len(a.split()) * 1.3 for a in self.alternatives)
        tokens += sum(len(u.split()) * 1.3 for u in self.uncertainties)
        tokens += sum(len(a.split()) * 1.3 for a in self.assumptions)
        tokens += sum(len(r.split()) * 1.3 for r in self.risks)
        tokens += sum(len(q.split()) * 1.3 for q in self.questions_for_team)
        if self.belief_state:
            tokens += sum(len(k.split()) * 1.3 for k in self.belief_state.knows)
            tokens += sum(len(b.split()) * 1.3 for b in self.belief_state.believes)
            tokens += sum(len(o.split()) * 1.3 for o in self.belief_state.others_likely_missing)
        return int(tokens)

    @classmethod
    def from_dict(cls, data: dict) -> "ContextPackage":
        """Deserialize from dict (e.g., from JSONL)."""
        belief_state = None
        if data.get("belief_state"):
            belief_state = BeliefState(**data["belief_state"])

        return cls(
            output=data.get("output", ""),
            agent_id=data.get("agent_id", "unknown"),
            model=data.get("model", "unknown"),
            reasoning=data.get("reasoning"),
            alternatives=data.get("alternatives", []),
            uncertainties=data.get("uncertainties", []),
            confidence=data.get("confidence"),
            assumptions=data.get("assumptions", []),
            risks=data.get("risks", []),
            dependencies=data.get("dependencies", []),
            files_examined=data.get("files_examined", []),
            questions_for_team=data.get("questions_for_team", []),
            belief_state=belief_state,
        )
