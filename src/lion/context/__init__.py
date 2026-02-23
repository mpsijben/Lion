"""Lion Context Ecosystem - Layer 2.

This module provides structured context sharing between agents:
- ContextPackage: Structured output from agents
- ContextMode: Context richness levels (minimal/standard/rich)
- BeliefState: Rich mode belief tracking
- parse_context_package: Parse structured agent output
- ContextAdapter: Format context for different LLMs
- ContextBudgetManager: Automatic context compression
- ContextArchaeologist: Search previous runs for relevant context
"""

from .package import ContextPackage, ContextMode, BeliefState
from .parser import parse_context_package, extract_sections, parse_list, estimate_tokens
from .adapter import ContextAdapter
from .budget import ContextBudgetManager, select_context_mode
from .archaeology import ContextArchaeologist, detect_relevant_files
from .lionmd import LionMdLoader, load_project_context, format_for_prompt
from .prompts import (
    PROPOSE_PROMPT_MINIMAL,
    PROPOSE_PROMPT_STANDARD,
    PROPOSE_PROMPT_RICH,
    CRITIQUE_PROMPT_MINIMAL,
    CRITIQUE_PROMPT_STANDARD,
    CRITIQUE_PROMPT_RICH,
    CONVERGE_PROMPT_MINIMAL,
    CONVERGE_PROMPT_STANDARD,
    CONVERGE_PROMPT_RICH,
    CONTEXT_PROMPT,
    DISTILL_PROMPT,
    DEVIL_PROMPT_WITH_CONFIDENCE,
    get_propose_prompt,
    get_critique_prompt,
    get_converge_prompt,
)

__all__ = [
    # Data types
    "ContextPackage",
    "ContextMode",
    "BeliefState",
    # Parsing
    "parse_context_package",
    "extract_sections",
    "parse_list",
    "estimate_tokens",
    # Adaptation
    "ContextAdapter",
    # Budget management
    "ContextBudgetManager",
    "select_context_mode",
    # Archaeology
    "ContextArchaeologist",
    "detect_relevant_files",
    # LION.md context
    "LionMdLoader",
    "load_project_context",
    "format_for_prompt",
    # Prompts
    "PROPOSE_PROMPT_MINIMAL",
    "PROPOSE_PROMPT_STANDARD",
    "PROPOSE_PROMPT_RICH",
    "CRITIQUE_PROMPT_MINIMAL",
    "CRITIQUE_PROMPT_STANDARD",
    "CRITIQUE_PROMPT_RICH",
    "CONVERGE_PROMPT_MINIMAL",
    "CONVERGE_PROMPT_STANDARD",
    "CONVERGE_PROMPT_RICH",
    "CONTEXT_PROMPT",
    "DISTILL_PROMPT",
    "DEVIL_PROMPT_WITH_CONFIDENCE",
    "get_propose_prompt",
    "get_critique_prompt",
    "get_converge_prompt",
]
