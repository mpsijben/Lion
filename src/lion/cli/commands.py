"""Command handlers for LionCLI.

Simple function-based command dispatch for the interactive REPL.
Each command is a function that takes (session, args) and prints output.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from .session import SessionState
from .views import ViewRenderer, get_terminal_width
from .rich_renderer import RICH_AVAILABLE, get_panel_renderer
from ..display import GREEN, YELLOW, RED, BLUE, CYAN, DIM, BOLD, RESET, MAGENTA
from ..memory import SharedMemory
from ..lenses import list_lenses, get_lens


def cmd_help(session: SessionState, args: list[str]) -> None:
    """Show help for all commands or a specific command."""
    if args:
        cmd_name = args[0]
        if cmd_name in COMMAND_HELP:
            info = COMMAND_HELP[cmd_name]
            print(f"\n{BOLD}:{cmd_name}{RESET} - {info['brief']}")
            print(f"\n{info['detail']}")
            if info.get("examples"):
                print(f"\n{BOLD}Examples:{RESET}")
                for example in info["examples"]:
                    print(f"  {DIM}{example}{RESET}")
            print()
        else:
            print(f"{RED}Unknown command: {cmd_name}{RESET}")
            print(f"Type {CYAN}:help{RESET} to see all commands.")
    else:
        print(f"\n{BOLD}LionCLI Commands{RESET}")
        print(f"{DIM}{'=' * 40}{RESET}\n")

        print(f"{BOLD}Inspection:{RESET}")
        print(f"  {CYAN}:inspect{RESET} [entry] [field]  - Inspect memory entries")
        print(f"  {CYAN}:memory{RESET} [--filter ...]    - Browse memory entries")
        print(f"  {CYAN}:reason{RESET} on|off|full       - Toggle reasoning display")

        print(f"\n{BOLD}History & Replay:{RESET}")
        print(f"  {CYAN}:history{RESET} [n]              - Show recent runs")
        print(f"  {CYAN}:replay{RESET} <run-id>          - Load a previous run")

        print(f"\n{BOLD}Configuration:{RESET}")
        print(f"  {CYAN}:config{RESET} [key]             - Show configuration")
        print(f"  {CYAN}:lens{RESET} [name]              - List or set active lens")
        print(f"  {CYAN}:debug{RESET} on|off             - Toggle debug mode")

        print(f"\n{BOLD}View Control:{RESET}")
        print(f"  {CYAN}:expand{RESET} <n> or {CYAN}:e{RESET} <n>    - Expand entry to full details")
        print(f"  {CYAN}:collapse{RESET} <n> or {CYAN}:c{RESET} <n>  - Collapse entry to summary")
        print(f"  {CYAN}:expand-all{RESET} / {CYAN}:ea{RESET}        - Expand all entries")
        print(f"  {CYAN}:collapse-all{RESET} / {CYAN}:ca{RESET}      - Collapse all entries")
        print(f"  {CYAN}:context{RESET} / {CYAN}:ctx{RESET}          - Show context summary")
        print(f"  {CYAN}:context-short{RESET} / {CYAN}:cs{RESET}     - Show one-line context summary")
        print(f"  {CYAN}:context-level{RESET} / {CYAN}:cl{RESET}     - Set context verbosity (minimal/normal/full)")
        print(f"  {CYAN}:cv{RESET}                       - Cycle context verbosity level")
        print(f"  {CYAN}:ct{RESET}                       - Toggle expand-all/collapse-all")
        print(f"  {CYAN}:prompt{RESET} default|enriched   - Toggle prompt style")

        print(f"\n{BOLD}Interactive Mode:{RESET}")
        print(f"  {CYAN}:interactive{RESET} on|off       - Toggle keyboard shortcut mode")
        print(f"  When on: {DIM}Ctrl+L{RESET} cycles verbosity, {DIM}Ctrl+T{RESET} toggles expand/collapse")

        print(f"\n{BOLD}Session:{RESET}")
        print(f"  {CYAN}:quit{RESET} or {CYAN}:q{RESET}              - Exit LionCLI")
        print(f"  {CYAN}:clear{RESET}                    - Clear current run")

        print(f"\n{DIM}Type :help <command> for detailed help.{RESET}")
        print(f"{DIM}Enter a prompt directly to execute a pipeline.{RESET}\n")


def cmd_quit(session: SessionState, args: list[str]) -> None:
    """Exit LionCLI."""
    print(f"\n{YELLOW}Goodbye!{RESET}\n")
    sys.exit(0)


def cmd_debug(session: SessionState, args: list[str]) -> None:
    """Toggle or set debug mode."""
    if not args:
        status = f"{GREEN}on{RESET}" if session.debug_mode else f"{DIM}off{RESET}"
        print(f"Debug mode: {status}")
        print(f"\n{DIM}Usage: :debug on|off{RESET}")
        return

    mode = args[0].lower()
    if mode == "on":
        session.debug_mode = True
        print(f"{GREEN}Debug mode enabled.{RESET}")
        print(f"  - Full tracebacks will be shown on errors")
        print(f"  - Provider stderr will be displayed")
    elif mode == "off":
        session.debug_mode = False
        print(f"Debug mode disabled.")
    else:
        print(f"{RED}Invalid option: {mode}{RESET}")
        print(f"Usage: :debug on|off")


def cmd_reason(session: SessionState, args: list[str]) -> None:
    """Toggle or set reasoning visibility mode."""
    if not args:
        mode_display = {
            "off": f"{DIM}off{RESET} - Summary only",
            "on": f"{GREEN}on{RESET} - Show reasoning inline",
            "full": f"{CYAN}full{RESET} - Show all Layer 2 fields",
        }
        print(f"Reasoning mode: {mode_display[session.reason_mode]}")
        print(f"\n{DIM}Usage: :reason off|on|full{RESET}")
        return

    mode = args[0].lower()
    if mode in ("off", "on", "full"):
        session.reason_mode = mode
        descriptions = {
            "off": "Summary only during execution",
            "on": "Reasoning shown inline during execution",
            "full": "All Layer 2 fields (reasoning, alternatives, uncertainties, confidence) shown inline",
        }
        print(f"Reasoning mode set to: {BOLD}{mode}{RESET}")
        print(f"  {descriptions[mode]}")
    else:
        print(f"{RED}Invalid mode: {mode}{RESET}")
        print(f"Usage: :reason off|on|full")


def cmd_inspect(session: SessionState, args: list[str]) -> None:
    """Inspect memory entries in the current run."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    entries = session.memory.read_all()

    if not entries:
        print(f"{YELLOW}No entries in this run.{RESET}")
        return

    if not args:
        # Show all entries respecting collapse state
        print(ViewRenderer.render_run_summary(
            session.get_run_id(),
            entries,
            session.memory.get_phases(),
            session.memory.get_agents(),
        ))
        print(f"\n{BOLD}Entries:{RESET}")

        # Use Rich panels if available
        terminal_width = get_terminal_width()
        if RICH_AVAILABLE:
            panel_renderer = get_panel_renderer()
            for i, entry in enumerate(entries):
                collapsed = session.is_collapsed(i)
                print(panel_renderer.render_entry_panel(
                    entry, i, collapsed=collapsed, terminal_width=terminal_width
                ))
            # Rich-styled footer hint
            collapsed_count = session.get_collapsed_count()
            print(f"\n{panel_renderer.render_footer_hint(collapsed_count, len(entries), terminal_width)}")
        else:
            for i, entry in enumerate(entries):
                collapsed = session.is_collapsed(i)
                print(ViewRenderer.render_entry(entry, i, collapsed=collapsed))
            # Show expand/collapse hint
            collapsed_count = session.get_collapsed_count()
            print(f"\n{ViewRenderer.render_expand_hint(collapsed_count, len(entries))}")
        return

    # Parse entry reference
    entry_ref = args[0]
    field = args[1] if len(args) > 1 else None

    # Handle step_N format or plain number
    if entry_ref.startswith("step_"):
        try:
            index = int(entry_ref[5:])
        except ValueError:
            print(f"{RED}Invalid entry reference: {entry_ref}{RESET}")
            return
    else:
        try:
            index = int(entry_ref)
        except ValueError:
            print(f"{RED}Invalid entry reference: {entry_ref}{RESET}")
            print(f"Use a number (e.g., :inspect 3) or step_N format (e.g., :inspect step_3)")
            return

    entry = session.memory.get_entry_by_index(index)
    if not entry:
        print(f"{RED}Entry {index} not found.{RESET}")
        print(f"Valid range: 0 to {len(entries) - 1}")
        return

    # Show specific field or full detail
    if field:
        field_lower = field.lower()
        if field_lower == "reasoning":
            print(ViewRenderer.render_reasoning(entry))
        elif field_lower == "alternatives":
            print(ViewRenderer.render_alternatives(entry))
        elif field_lower == "uncertainties":
            print(ViewRenderer.render_uncertainties(entry))
        elif field_lower == "confidence":
            print(ViewRenderer.render_confidence(entry))
        else:
            print(f"{RED}Unknown field: {field}{RESET}")
            print(f"Available fields: reasoning, alternatives, uncertainties, confidence")
    else:
        print(ViewRenderer.render_step_detail(entry, index))


def cmd_memory(session: SessionState, args: list[str]) -> None:
    """Browse memory entries with optional filtering."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    entries = session.memory.read_all()

    # Parse filter arguments
    filter_agent = None
    filter_phase = None

    i = 0
    while i < len(args):
        if args[i] == "--filter" and i + 1 < len(args):
            filter_agent = args[i + 1]
            i += 2
        elif args[i] == "--phase" and i + 1 < len(args):
            filter_phase = args[i + 1]
            i += 2
        else:
            i += 1

    # Cache all entries for index lookup before filtering
    all_entries = list(entries)
    entry_to_index = {id(e): i for i, e in enumerate(all_entries)}

    # Apply filters
    if filter_agent:
        entries = [e for e in entries if filter_agent in e.agent]
    if filter_phase:
        entries = [e for e in entries if e.phase == filter_phase]

    if not entries:
        print(f"{YELLOW}No entries match the filter.{RESET}")
        return

    # Show filtered entries
    print(f"\n{BOLD}Memory Entries{RESET}")
    if filter_agent or filter_phase:
        filters = []
        if filter_agent:
            filters.append(f"agent={filter_agent}")
        if filter_phase:
            filters.append(f"phase={filter_phase}")
        print(f"{DIM}Filters: {', '.join(filters)}{RESET}")

    print(f"{DIM}{'=' * 50}{RESET}\n")

    terminal_width = get_terminal_width()

    if RICH_AVAILABLE:
        panel_renderer = get_panel_renderer()
        for entry in entries:
            orig_index = entry_to_index.get(id(entry), 0)
            collapsed = session.is_collapsed(orig_index)
            print(panel_renderer.render_entry_panel(
                entry, orig_index, collapsed=collapsed, terminal_width=terminal_width
            ))
        # Rich-styled footer hint
        collapsed_count = session.get_collapsed_count()
        print(f"\n{panel_renderer.render_footer_hint(collapsed_count, len(all_entries), terminal_width)}")
    else:
        for entry in entries:
            orig_index = entry_to_index.get(id(entry), 0)
            collapsed = session.is_collapsed(orig_index)
            print(ViewRenderer.render_entry(entry, orig_index, collapsed=collapsed))
        # Show expand/collapse hint
        collapsed_count = session.get_collapsed_count()
        print(f"\n{ViewRenderer.render_expand_hint(collapsed_count, len(all_entries))}")

    print(f"{DIM}Use :memory --filter <agent> or --phase <phase> to filter.{RESET}")


def cmd_history(session: SessionState, args: list[str]) -> None:
    """Show recent runs."""
    # Parse limit argument
    limit = 10
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            print(f"{RED}Invalid limit: {args[0]}{RESET}")
            return

    # Find .lion/runs directory
    runs_dir = session.cwd / ".lion" / "runs"
    if not runs_dir.exists():
        print(f"{YELLOW}No runs found in {runs_dir}{RESET}")
        return

    # List run directories sorted by modification time
    runs = []
    try:
        for run_dir in runs_dir.iterdir():
            if run_dir.is_dir():
                memory_file = run_dir / "memory.jsonl"
                if memory_file.exists():
                    mtime = memory_file.stat().st_mtime
                    runs.append((run_dir, mtime))
    except PermissionError:
        print(f"{RED}Permission denied accessing runs directory{RESET}")
        return

    runs.sort(key=lambda x: x[1], reverse=True)
    runs = runs[:limit]

    if not runs:
        print(f"{YELLOW}No runs found.{RESET}")
        return

    print(f"\n{BOLD}Recent Runs{RESET}")
    print(f"{DIM}{'=' * 60}{RESET}\n")

    for run_dir, mtime in runs:
        timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

        # Try to count entries
        try:
            memory = SharedMemory.load(run_dir)
            entry_count = memory.count()
            entry_str = f"{entry_count} entries"
        except Exception:
            entry_str = "?"

        # Highlight current run
        if session.run_dir and run_dir == session.run_dir:
            marker = f" {GREEN}<- current{RESET}"
        else:
            marker = ""

        print(f"  {CYAN}{run_dir.name}{RESET}")
        print(f"    {DIM}{timestamp} | {entry_str}{RESET}{marker}")

    print(f"\n{DIM}Use :replay <run-id> to load a run.{RESET}")


def cmd_replay(session: SessionState, args: list[str]) -> None:
    """Load a previous run for inspection."""
    if not args:
        print(f"{YELLOW}Usage: :replay <run-id>{RESET}")
        print(f"Use {CYAN}:history{RESET} to see available runs.")
        return

    run_ref = args[0]
    runs_dir = session.cwd / ".lion" / "runs"

    # Handle "latest" special case
    if run_ref == "latest":
        if not runs_dir.exists():
            print(f"{RED}No runs directory found.{RESET}")
            return

        runs = []
        try:
            for run_dir in runs_dir.iterdir():
                if run_dir.is_dir() and (run_dir / "memory.jsonl").exists():
                    mtime = (run_dir / "memory.jsonl").stat().st_mtime
                    runs.append((run_dir, mtime))
        except PermissionError:
            print(f"{RED}Permission denied accessing runs directory{RESET}")
            return

        if not runs:
            print(f"{RED}No runs found.{RESET}")
            return

        runs.sort(key=lambda x: x[1], reverse=True)
        run_dir = runs[0][0]
    else:
        # Try as full path first
        run_dir = Path(run_ref)
        if not run_dir.exists():
            # Try as run ID within .lion/runs
            run_dir = runs_dir / run_ref

    if not run_dir.exists():
        print(f"{RED}Run not found: {run_ref}{RESET}")
        print(f"Use {CYAN}:history{RESET} to see available runs.")
        return

    if session.load_run(run_dir):
        entries = session.memory.read_all()
        phases = session.memory.get_phases()
        agents = session.memory.get_agents()

        print(f"{GREEN}Loaded run: {run_dir.name}{RESET}")
        print(f"  Entries: {len(entries)}")
        print(f"  Phases:  {', '.join(phases)}")
        print(f"  Agents:  {', '.join(agents)}")
        print(f"\n{DIM}Use :inspect to explore entries.{RESET}")
    else:
        print(f"{RED}Failed to load run: {run_ref}{RESET}")
        print(f"The run directory may be missing memory.jsonl.")


def cmd_config(session: SessionState, args: list[str]) -> None:
    """Show configuration."""
    if not args:
        print(f"\n{BOLD}Configuration{RESET}")
        print(f"{DIM}{'=' * 40}{RESET}\n")

        if session.config_path:
            print(f"Loaded from: {CYAN}{session.config_path}{RESET}")
        else:
            print(f"Loaded from: {DIM}(defaults){RESET}")

        print()
        _print_config(session.config, indent=0)
        return

    # Show specific key
    key = args[0]
    value = session.config.get(key)
    if value is not None:
        if isinstance(value, dict):
            print(f"\n{BOLD}[{key}]{RESET}")
            _print_config(value, indent=2)
        else:
            print(f"{key} = {value}")
    else:
        print(f"{YELLOW}Key not found: {key}{RESET}")
        print(f"Available keys: {', '.join(session.config.keys())}")


def _print_config(config: dict, indent: int = 0) -> None:
    """Print config dict with formatting."""
    prefix = " " * indent
    for key, value in config.items():
        if isinstance(value, dict):
            print(f"{prefix}{BOLD}[{key}]{RESET}")
            _print_config(value, indent + 2)
        else:
            print(f"{prefix}{DIM}{key}:{RESET} {value}")


def cmd_lens(session: SessionState, args: list[str]) -> None:
    """List available lenses or set active lens."""
    if not args:
        # List all lenses
        lenses = list_lenses()
        print(f"\n{BOLD}Available Lenses{RESET}")
        print(f"{DIM}{'=' * 40}{RESET}\n")

        for lens in lenses:
            marker = ""
            if session.current_lens == lens.shortcode:
                marker = f" {GREEN}<- active{RESET}"

            print(f"  {CYAN}{lens.shortcode}{RESET} - {lens.name}{marker}")
            # Show first line of prompt inject
            first_line = lens.prompt_inject.split("\n")[0][:60]
            print(f"    {DIM}{first_line}...{RESET}")

        print(f"\n{DIM}Use :lens <shortcode> to set active lens.{RESET}")
        print(f"{DIM}Use :lens off to clear.{RESET}")
        return

    lens_name = args[0].lower()

    if lens_name == "off":
        session.current_lens = None
        print(f"Lens cleared. Next pipeline will use default behavior.")
        return

    lens = get_lens(lens_name)
    if lens:
        session.current_lens = lens.shortcode
        print(f"{GREEN}Lens set: {lens.name} ({lens.shortcode}){RESET}")
        print(f"\nThis lens will be applied to the next pipeline execution.")
        print(f"\n{BOLD}Focus:{RESET}")
        for line in lens.prompt_inject.split("\n")[:5]:
            print(f"  {line}")
        if len(lens.prompt_inject.split("\n")) > 5:
            print(f"  {DIM}...{RESET}")
    else:
        print(f"{RED}Unknown lens: {lens_name}{RESET}")
        print(f"Use {CYAN}:lens{RESET} to see available lenses.")


def cmd_clear(session: SessionState, args: list[str]) -> None:
    """Clear the current run from session."""
    if session.has_run():
        run_id = session.get_run_id()
        session.clear_run()
        print(f"Cleared run: {run_id}")
    else:
        print(f"{DIM}No run loaded.{RESET}")


def cmd_expand(session: SessionState, args: list[str]) -> None:
    """Expand one or all entries to show full details."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    entries = session.memory.read_all()

    if not entries:
        print(f"{YELLOW}No entries to expand.{RESET}")
        return

    if not args:
        # Show current state and usage
        total = len(entries)
        collapsed = session.get_collapsed_count()
        expanded = total - collapsed
        print(f"Entries: {total} total, {expanded} expanded, {collapsed} collapsed")
        print(f"\n{DIM}Usage:{RESET}")
        print(f"  {CYAN}:expand <n>{RESET}     Expand entry n to show full details")
        print(f"  {CYAN}:expand-all{RESET}    Expand all entries")
        print(f"  {CYAN}:collapse <n>{RESET}  Collapse entry n to summary view")
        print(f"  {CYAN}:collapse-all{RESET}  Collapse all entries")
        return

    # Parse entry reference
    entry_ref = args[0]

    try:
        index = int(entry_ref)
    except ValueError:
        print(f"{RED}Invalid entry reference: {entry_ref}{RESET}")
        print(f"Use a number (e.g., :expand 3)")
        return

    if index < 0 or index >= len(entries):
        print(f"{RED}Entry {index} not found.{RESET}")
        print(f"Valid range: 0 to {len(entries) - 1}")
        return

    # Expand the entry
    session.expand_entry(index)
    entry = entries[index]

    # Show the expanded entry
    print(f"{GREEN}Expanded entry {index}{RESET}")
    print(ViewRenderer.render_step_detail(entry, index))


def cmd_expand_all(session: SessionState, args: list[str]) -> None:
    """Expand all entries to show full details."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    session.expand_all()
    entries = session.memory.read_all()
    print(f"{GREEN}Expanded all {len(entries)} entries.{RESET}")
    print(f"\n{DIM}Use :inspect to view entries, or :collapse-all to collapse.{RESET}")


def cmd_collapse(session: SessionState, args: list[str]) -> None:
    """Collapse one or all entries to summary view."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    entries = session.memory.read_all()

    if not entries:
        print(f"{YELLOW}No entries to collapse.{RESET}")
        return

    if not args:
        # Show current state and usage
        total = len(entries)
        collapsed = session.get_collapsed_count()
        expanded = total - collapsed
        print(f"Entries: {total} total, {expanded} expanded, {collapsed} collapsed")
        print(f"\n{DIM}Usage:{RESET}")
        print(f"  {CYAN}:collapse <n>{RESET}  Collapse entry n to summary view")
        print(f"  {CYAN}:collapse-all{RESET}  Collapse all entries")
        print(f"  {CYAN}:expand <n>{RESET}    Expand entry n to show full details")
        print(f"  {CYAN}:expand-all{RESET}    Expand all entries")
        return

    # Parse entry reference
    entry_ref = args[0]

    try:
        index = int(entry_ref)
    except ValueError:
        print(f"{RED}Invalid entry reference: {entry_ref}{RESET}")
        print(f"Use a number (e.g., :collapse 3)")
        return

    if index < 0 or index >= len(entries):
        print(f"{RED}Entry {index} not found.{RESET}")
        print(f"Valid range: 0 to {len(entries) - 1}")
        return

    # Collapse the entry
    session.collapse_entry(index)
    entry = entries[index]

    # Show the collapsed entry with hint
    print(f"Collapsed entry {index}")
    print(ViewRenderer.render_step_summary(entry, index, collapsed=True))


def cmd_collapse_all(session: SessionState, args: list[str]) -> None:
    """Collapse all entries to summary view."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    session.collapse_all()
    entries = session.memory.read_all()
    print(f"Collapsed all {len(entries)} entries.")
    print(f"\n{DIM}Use :expand <n> to expand specific entries, or :expand-all to expand all.{RESET}")


def cmd_context_short(session: SessionState, args: list[str]) -> None:
    """Show condensed one-line context summary."""
    entries = session.memory.read_all() if session.has_run() else []
    total_chars = sum(len(e.content) for e in entries)
    print(ViewRenderer.render_context_short(len(entries), total_chars, session.has_run()))


def cmd_context(session: SessionState, args: list[str]) -> None:
    """Show current session context summary based on context_level setting."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    entries = session.memory.read_all()

    # Render context based on verbosity level
    print(ViewRenderer.render_context_at_level(entries, session.context_level))

    # Always show session info regardless of level
    print()

    # Build lens info
    if session.current_lens:
        lens_str = f"{CYAN}{session.current_lens}{RESET}"
    else:
        lens_str = f"{DIM}none{RESET}"

    # Build reason mode info
    reason_colors = {
        "off": DIM,
        "on": GREEN,
        "full": CYAN,
    }
    reason_color = reason_colors.get(session.reason_mode, DIM)
    reason_str = f"{reason_color}{session.reason_mode}{RESET}"

    # Build context level info
    level_colors = {
        "minimal": DIM,
        "normal": GREEN,
        "full": CYAN,
    }
    level_color = level_colors.get(session.context_level, DIM)
    level_str = f"{level_color}{session.context_level}{RESET}"

    # Print session info
    print(f"{DIM}Session:{RESET}")
    print(f"  lens: {lens_str} | reason: {reason_str} | context-level: {level_str}")

    # Build run info
    run_id = session.get_run_id()
    run_str = f"{CYAN}{run_id[:30]}{RESET}" if len(run_id) > 30 else f"{CYAN}{run_id}{RESET}"
    print(f"  run: {run_str}")

    # Collapse/expand status
    total = len(entries)
    collapsed = session.get_collapsed_count()
    expanded = total - collapsed
    print(f"  view: {expanded} expanded, {collapsed} collapsed")

    # Only show Layer 2 summary in normal/full mode
    if session.context_level != "minimal":
        with_reasoning = sum(1 for e in entries if e.reasoning)
        with_alternatives = sum(1 for e in entries if e.alternatives)
        with_confidence = sum(1 for e in entries if e.confidence is not None)

        if with_reasoning or with_alternatives or with_confidence:
            print(f"\n{BOLD}Layer 2 Data:{RESET}")
            if with_reasoning:
                print(f"  {MAGENTA}reasoning:{RESET} {with_reasoning} entries")
            if with_alternatives:
                print(f"  {YELLOW}alternatives:{RESET} {with_alternatives} entries")
            if with_confidence:
                print(f"  {GREEN}confidence:{RESET} {with_confidence} entries")

    # Show hint for changing context level
    print(f"\n{DIM}Use :context-level minimal|normal|full to change verbosity.{RESET}")
    print()


def cmd_prompt(session: SessionState, args: list[str]) -> None:
    """Toggle prompt style between default and enriched."""
    if not args:
        current = session.prompt_style
        print(f"Prompt style: {BOLD}{current}{RESET}")
        print(f"\n{DIM}Usage: :prompt default|enriched{RESET}")
        print(f"\n  default  - Simple 'lion>' prompt")
        print(f"  enriched - Shows lens, reason mode, and entry count")
        return

    style = args[0].lower()
    if style in ("default", "enriched"):
        session.prompt_style = style
        if style == "enriched":
            print(f"{GREEN}Prompt style set to enriched.{RESET}")
            print(f"Prompt will show: lion [lens|reason|entries]>")
        else:
            print(f"Prompt style set to default.")
            print(f"Prompt will show: lion>")
    else:
        print(f"{RED}Invalid style: {style}{RESET}")
        print(f"Usage: :prompt default|enriched")


def cmd_context_level(session: SessionState, args: list[str]) -> None:
    """Set or show context verbosity level."""
    if not args:
        # Show current level + help text
        level_display = {
            "minimal": f"{DIM}minimal{RESET} - Token count only (fastest)",
            "normal": f"{GREEN}normal{RESET} - Entry names + token counts (default)",
            "full": f"{CYAN}full{RESET} - Complete context with content preview",
        }
        current_marker = {
            "minimal": " <- current" if session.context_level == "minimal" else "",
            "normal": " <- current" if session.context_level == "normal" else "",
            "full": " <- current" if session.context_level == "full" else "",
        }
        print(f"Context level: {BOLD}{session.context_level}{RESET}")
        print(f"\n{BOLD}Levels:{RESET}")
        print(f"  minimal - Token count only (fastest){GREEN}{current_marker['minimal']}{RESET}")
        print(f"  normal  - Entry names + token counts (default){GREEN}{current_marker['normal']}{RESET}")
        print(f"  full    - Complete context with content preview{GREEN}{current_marker['full']}{RESET}")
        print(f"\n{DIM}Usage: :context-level minimal|normal|full{RESET}")
        return

    level = args[0].lower()
    if level in ("minimal", "normal", "full"):
        session.context_level = level
        descriptions = {
            "minimal": "Token count only (fastest rendering)",
            "normal": "Entry names + token counts (default)",
            "full": "Complete context with content preview",
        }
        print(f"{GREEN}Context level set to: {BOLD}{level}{RESET}")
        print(f"  {descriptions[level]}")
        print(f"\n{DIM}Note: This setting is session-only. To persist, add to config.toml:{RESET}")
        print(f"{DIM}  [cli]{RESET}")
        print(f"{DIM}  context_level = \"{level}\"{RESET}")
    else:
        print(f"{RED}Invalid level: {level}{RESET}")
        print(f"Valid levels: minimal, normal, full")
        print(f"Usage: :context-level minimal|normal|full")


def cmd_cycle_verbosity(session: SessionState, args: list[str]) -> None:
    """Cycle through context verbosity levels (minimal -> normal -> full -> minimal)."""
    new_level = session.cycle_context_verbosity()
    level_descriptions = {
        "minimal": "token count only",
        "normal": "entry names + token counts",
        "full": "content preview + Layer 2 indicators",
    }
    print(f"Context verbosity: {BOLD}{new_level}{RESET} ({level_descriptions[new_level]})")


def cmd_context_toggle(session: SessionState, args: list[str]) -> None:
    """Toggle between expand-all and collapse-all states."""
    if not session.has_run():
        print(f"{YELLOW}No run loaded.{RESET}")
        print(f"Use {CYAN}:replay <run-id>{RESET} to load a previous run,")
        print(f"or execute a pipeline first.")
        return

    action = session.toggle_expand_collapse_all()
    entries = session.memory.read_all()
    total = len(entries)

    if action == "expanded":
        print(f"{GREEN}Expanded all {total} entries.{RESET}")
    else:
        print(f"Collapsed all {total} entries.")

    # Show status line
    print(ViewRenderer.render_status_line(session))


def cmd_interactive(session: SessionState, args: list[str]) -> None:
    """Toggle or set interactive mode for keyboard shortcuts."""
    if not args:
        status = f"{GREEN}on{RESET}" if session.interactive_mode else f"{DIM}off{RESET}"
        print(f"Interactive mode: {status}")
        print(f"\n{DIM}Usage: :interactive on|off{RESET}")
        print()
        print(f"When ON, keyboard shortcuts are available during prompt input:")
        print(f"  {CYAN}Ctrl+L{RESET} - Cycle context verbosity (minimal/normal/full)")
        print(f"  {CYAN}Ctrl+T{RESET} - Toggle expand-all/collapse-all")
        return

    mode = args[0].lower()
    if mode == "on":
        session.interactive_mode = True
        print(f"{GREEN}Interactive mode enabled.{RESET}")
        print()
        print(f"Keyboard shortcuts now active during prompt input:")
        print(f"  {CYAN}Ctrl+L{RESET} - Cycle context verbosity")
        print(f"  {CYAN}Ctrl+T{RESET} - Toggle expand-all/collapse-all")
        print()
        print(f"{DIM}Note: Shortcuts are detected when you press Enter.{RESET}")
    elif mode == "off":
        session.interactive_mode = False
        print(f"Interactive mode disabled.")
        print(f"Keyboard shortcuts are no longer active.")
    else:
        print(f"{RED}Invalid option: {mode}{RESET}")
        print(f"Usage: :interactive on|off")


# Command dispatch table
COMMANDS: dict[str, Callable[[SessionState, list[str]], None]] = {
    "help": cmd_help,
    "h": cmd_help,
    "quit": cmd_quit,
    "q": cmd_quit,
    "exit": cmd_quit,
    "debug": cmd_debug,
    "reason": cmd_reason,
    "inspect": cmd_inspect,
    "i": cmd_inspect,
    "memory": cmd_memory,
    "mem": cmd_memory,
    "history": cmd_history,
    "hist": cmd_history,
    "replay": cmd_replay,
    "config": cmd_config,
    "cfg": cmd_config,
    "lens": cmd_lens,
    "clear": cmd_clear,
    # Expand/collapse commands
    "expand": cmd_expand,
    "e": cmd_expand,
    "expand-all": cmd_expand_all,
    "ea": cmd_expand_all,
    "collapse": cmd_collapse,
    "c": cmd_collapse,
    "collapse-all": cmd_collapse_all,
    "ca": cmd_collapse_all,
    # Context and status commands
    "context": cmd_context,
    "ctx": cmd_context,
    "status": cmd_context,
    "context-short": cmd_context_short,
    "cs": cmd_context_short,
    "prompt": cmd_prompt,
    # Context verbosity level
    "context-level": cmd_context_level,
    "cl": cmd_context_level,
    # Quick toggle commands
    "cv": cmd_cycle_verbosity,
    "cycle-verbosity": cmd_cycle_verbosity,
    "ct": cmd_context_toggle,
    "context-toggle": cmd_context_toggle,
    # Interactive mode
    "interactive": cmd_interactive,
}


# Detailed help for each command
COMMAND_HELP = {
    "help": {
        "brief": "Show help for commands",
        "detail": "Shows a list of all available commands or detailed help for a specific command.",
        "examples": [":help", ":help inspect"],
    },
    "quit": {
        "brief": "Exit LionCLI",
        "detail": "Exits the interactive session. You can also use Ctrl+D.",
        "examples": [":quit", ":q"],
    },
    "debug": {
        "brief": "Toggle debug mode",
        "detail": """Debug mode controls error verbosity.

When ON:
  - Full stack traces are shown for errors
  - Provider stderr output is displayed
  - Internal state information is available

When OFF:
  - Only user-friendly error messages are shown""",
        "examples": [":debug on", ":debug off", ":debug"],
    },
    "reason": {
        "brief": "Toggle reasoning visibility",
        "detail": """Controls how reasoning information is displayed during pipeline execution.

Modes:
  off  - Summary only (default)
  on   - Show reasoning inline during execution
  full - Show all Layer 2 fields (reasoning, alternatives, uncertainties, confidence)

This affects both streaming output during execution and the default inspection detail level.""",
        "examples": [":reason on", ":reason full", ":reason off"],
    },
    "inspect": {
        "brief": "Inspect memory entries",
        "detail": """Shows detailed information about memory entries in the current run.

Without arguments, shows a summary of all entries.
With an entry number, shows full details for that entry.
With a field name, shows only that specific field.

Available fields:
  reasoning     - WHY this approach was chosen
  alternatives  - What was considered but rejected
  uncertainties - What the agent is unsure about
  confidence    - Confidence score (0-100%)""",
        "examples": [
            ":inspect",
            ":inspect 3",
            ":inspect step_3",
            ":inspect 3 reasoning",
            ":inspect 3 alternatives",
        ],
    },
    "memory": {
        "brief": "Browse memory entries",
        "detail": """Lists memory entries with optional filtering.

Filters:
  --filter <agent>  Filter by agent name (partial match)
  --phase <phase>   Filter by phase name (exact match)

Phases include: propose, critique, converge, implement, etc.
Agents are named like: agent_1, agent_2, synthesizer, etc.""",
        "examples": [
            ":memory",
            ":memory --filter agent_1",
            ":memory --phase propose",
            ":memory --filter agent --phase critique",
        ],
    },
    "history": {
        "brief": "Show recent runs",
        "detail": """Lists recent pipeline runs from .lion/runs/ directory.

Each run shows its ID (directory name), timestamp, and entry count.
Use :replay to load a specific run for inspection.""",
        "examples": [":history", ":history 5", ":history 20"],
    },
    "replay": {
        "brief": "Load a previous run",
        "detail": """Loads a previous run for inspection.

After loading, use :inspect and :memory to explore the run's memory entries.
Use 'latest' to load the most recent run.""",
        "examples": [
            ":replay latest",
            ":replay 2024-01-15_120530_Build_auth_system",
        ],
    },
    "config": {
        "brief": "Show configuration",
        "detail": """Displays the current Lion configuration.

Without arguments, shows all configuration.
With a key, shows just that section.""",
        "examples": [":config", ":config providers", ":config context"],
    },
    "lens": {
        "brief": "List or set active lens",
        "detail": """Manages the active lens for pipeline execution.

A lens focuses agent attention on a specific dimension like architecture,
security, or performance. When set, the lens will be applied to the next
pipeline execution.

Use ':lens off' to clear the active lens.""",
        "examples": [":lens", ":lens arch", ":lens sec", ":lens off"],
    },
    "clear": {
        "brief": "Clear current run",
        "detail": "Clears the currently loaded run from the session. Use :replay to load another run.",
        "examples": [":clear"],
    },
    "expand": {
        "brief": "Expand entry to full details",
        "detail": """Expand a specific memory entry to show all Layer 2 fields.

When viewing memory entries, they are collapsed by default showing only a summary.
Use :expand to see the full content, reasoning, alternatives, uncertainties, and confidence.

Aliases: :e""",
        "examples": [":expand 3", ":e 0", ":expand"],
    },
    "expand-all": {
        "brief": "Expand all entries",
        "detail": """Expand all memory entries to show full details.

After expanding, use :inspect to view all entries in full, or :collapse-all to collapse them back.

Aliases: :ea""",
        "examples": [":expand-all", ":ea"],
    },
    "collapse": {
        "brief": "Collapse entry to summary",
        "detail": """Collapse a specific memory entry to show only a summary.

Collapsed entries show a one-line summary with a [+N] indicator.
Use :expand N to see the full content again.

Aliases: :c""",
        "examples": [":collapse 3", ":c 0", ":collapse"],
    },
    "collapse-all": {
        "brief": "Collapse all entries",
        "detail": """Collapse all memory entries to summary view.

This is the default state. Each entry shows a one-line summary with [+N] indicator.
Use :expand N or :expand-all to see full details.

Aliases: :ca""",
        "examples": [":collapse-all", ":ca"],
    },
    "context": {
        "brief": "Show context summary",
        "detail": """Shows a one-line summary of the current session context.

Displays:
  - Active lens (if set)
  - Reason mode (off, on, full)
  - Current run and entry count
  - Layer 2 data availability
  - Prompt style and debug mode

Aliases: :ctx, :status""",
        "examples": [":context", ":ctx", ":status"],
    },
    "context-short": {
        "brief": "Show condensed one-line context summary",
        "detail": """Shows a condensed one-line summary of the current context.

Output format: "Context: N entries, Xk tokens"

This is useful for quick status checks or scripting. The token count is
an approximation based on character count (chars / 4).

Also available as CLI flag: lioncli --context-short (or -cs)

Aliases: :cs""",
        "examples": [":context-short", ":cs"],
    },
    "prompt": {
        "brief": "Toggle prompt style",
        "detail": """Toggle between default and enriched prompt styles.

Styles:
  default  - Simple 'lion>' prompt
  enriched - Shows lens, reason mode, and entry count: 'lion [lens|reason|N]>'

The enriched prompt gives at-a-glance context without running :context.""",
        "examples": [":prompt", ":prompt enriched", ":prompt default"],
    },
    "context-level": {
        "brief": "Set context display verbosity",
        "detail": """Set the verbosity level for context display.

Levels:
  minimal - Token count only (fastest rendering)
  normal  - Entry names + token counts (default)
  full    - Complete context with content preview and Layer 2 indicators

Without arguments, shows the current level and available options.

This setting affects the :context command output. It can also be set via
the --context-level CLI flag or persisted in config.toml:

  [cli]
  context_level = "normal"

Aliases: :cl""",
        "examples": [
            ":context-level",
            ":context-level minimal",
            ":context-level normal",
            ":context-level full",
            ":cl full",
        ],
    },
    "cv": {
        "brief": "Cycle context verbosity",
        "detail": """Quickly cycle through context verbosity levels.

Cycles through: minimal -> normal -> full -> minimal

This is a quick way to change verbosity without specifying a level.
Equivalent to pressing Ctrl+L in interactive mode.

Aliases: :cycle-verbosity""",
        "examples": [":cv"],
    },
    "ct": {
        "brief": "Toggle expand-all/collapse-all",
        "detail": """Quickly toggle between expanded and collapsed view of all entries.

If any entries are collapsed, expands all entries.
If all entries are expanded, collapses all entries.

This is a quick way to toggle view state without specifying individual entries.
Equivalent to pressing Ctrl+T in interactive mode.

Aliases: :context-toggle""",
        "examples": [":ct"],
    },
    "interactive": {
        "brief": "Toggle interactive mode",
        "detail": """Enable or disable keyboard shortcuts during prompt input.

When interactive mode is ON, you can use keyboard shortcuts:
  Ctrl+L - Cycle context verbosity (minimal/normal/full)
  Ctrl+T - Toggle expand-all/collapse-all

These shortcuts are detected via readline key bindings and execute
when you press Enter. This allows quick toggling without typing commands.

Without arguments, shows current mode and available shortcuts.""",
        "examples": [
            ":interactive",
            ":interactive on",
            ":interactive off",
        ],
    },
}


def handle_command(session: SessionState, line: str) -> None:
    """Dispatch a command to the appropriate handler.

    Args:
        session: Current session state
        line: Command line starting with ':'
    """
    # Remove ':' prefix and split
    parts = line[1:].split()
    cmd_name = parts[0].lower() if parts else "help"
    args = parts[1:]

    if cmd_name in COMMANDS:
        COMMANDS[cmd_name](session, args)
    else:
        print(f"{RED}Unknown command: {cmd_name}{RESET}")
        print(f"Type {CYAN}:help{RESET} for available commands.")
