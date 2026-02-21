"""LionCLI - Interactive Reasoning Explorer for Lion.

An interactive CLI that exposes Lion's Layer 2 reasoning data
(reasoning, alternatives, uncertainties, confidence) through
an intuitive REPL interface.

Features:
    - Collapsible/expandable context display with Rich panels
    - Per-entry expand/collapse with :expand/:collapse commands
    - Context summary with :context command
    - Terminal-aware responsive rendering

Usage:
    lioncli              # Start interactive REPL
    lioncli --debug      # Start with debug mode enabled
"""

from .repl import main
from .rich_renderer import RICH_AVAILABLE, get_panel_renderer, get_terminal_width

__all__ = ["main", "RICH_AVAILABLE", "get_panel_renderer", "get_terminal_width"]
