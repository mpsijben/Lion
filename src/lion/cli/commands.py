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
from ..status import StatusDashboard
from ..session import SessionManager


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

        print(f"\n{BOLD}Session History (with Git commits):{RESET}")
        print(f"  {CYAN}:sessions{RESET} [n]             - Show pipeline sessions with commits")
        print(f"  {CYAN}:session-detail{RESET} <id>      - Show session step-by-step commits")
        print(f"  {CYAN}:session-resume{RESET} <id> --from <step>  - Resume from a step")
        print(f"  {CYAN}:session-replay{RESET} <id>      - Read-only replay of session")
        print(f"  {CYAN}:session-prune{RESET} [--keep n] - Clean up old sessions")

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

        print(f"\n{BOLD}Status & Quota:{RESET}")
        print(f"  {CYAN}:dashboard{RESET} or {CYAN}:dash{RESET}      - Show status dashboard (quota, sessions, active)")
        print(f"  {CYAN}:quota{RESET}                    - Alias for :dashboard")

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


def cmd_status_dashboard(session: SessionState, args: list[str]) -> None:
    """Show the Lion status dashboard with quota, sessions, and active pipelines.

    Always uses ~/.lion for global data (quota, overall sessions) to ensure
    consistent behavior across directories. This avoids confusion where
    running 'lion status' from different directories shows different data.
    """
    # Parse arguments
    use_json = "--json" in args or "-j" in args
    show_local = "--local" in args or "-l" in args

    # Always use home directory for consistent global data
    # This ensures quota tracking and session history are not fragmented
    # across different project directories.
    home_lion_dir = Path.home() / ".lion"
    home_runs_dir = home_lion_dir / "runs"

    # Optionally show local project data if --local flag is passed
    if show_local:
        local_lion_dir = session.cwd / ".lion"
        if local_lion_dir.exists():
            dashboard = StatusDashboard(
                config=session.config,
                runs_dir=local_lion_dir / "runs",
                lion_dir=local_lion_dir,
            )
            data_source = f"{local_lion_dir} (local project)"
        else:
            print(f"{YELLOW}No local .lion directory found in {session.cwd}{RESET}")
            print(f"Use {CYAN}:dashboard{RESET} without --local to see global data from ~/.lion")
            return
    else:
        dashboard = StatusDashboard(
            config=session.config,
            runs_dir=home_runs_dir,
            lion_dir=home_lion_dir,
        )
        data_source = f"{home_lion_dir} (global)"

    output = dashboard.render(use_json=use_json)
    print(output)

    # Show data source for user clarity (not in JSON mode)
    if not use_json:
        print(f"{DIM}Data source: {data_source}{RESET}")
        if not show_local:
            local_lion_dir = session.cwd / ".lion"
            if local_lion_dir.exists():
                print(f"{DIM}Tip: Use --local to see data from this project's .lion directory{RESET}")

# =============================================================================
# Session History Commands (lion history, lion resume, lion replay)
# =============================================================================


def _validate_positive_int(value: str, name: str, max_value: int = 1000) -> int | None:
    """Validate and parse a positive integer from CLI input.

    Args:
        value: String value to parse
        name: Parameter name for error messages
        max_value: Maximum allowed value

    Returns:
        Parsed integer or None if invalid (error already printed)
    """
    try:
        num = int(value)
    except ValueError:
        print(f"{RED}Invalid {name}: '{value}' is not a number.{RESET}")
        print(f"Please enter a positive integer (e.g., 1, 5, 10).")
        return None

    if num < 1:
        print(f"{RED}Invalid {name}: must be at least 1, got {num}.{RESET}")
        return None

    if num > max_value:
        print(f"{RED}Invalid {name}: {num} exceeds maximum of {max_value}.{RESET}")
        return None

    return num


def cmd_session_history(session: SessionState, args: list[str]) -> None:
    """Show pipeline session history with commit hashes.

    This shows sessions from ~/.lion/sessions/ which track pipeline
    execution with git commit hashes at each step.
    """
    # Parse and validate limit argument
    limit = 10
    if args:
        validated = _validate_positive_int(args[0], "limit", max_value=500)
        if validated is None:
            return
        limit = validated

    manager = SessionManager()
    sessions = manager.list_sessions(limit=limit)

    if not sessions:
        print(f"{YELLOW}No sessions found.{RESET}")
        print(f"\nSessions are created when you run pipelines with session tracking enabled.")
        return

    print(f"\n{BOLD}Pipeline Session History{RESET}")
    print(f"{DIM}{'=' * 70}{RESET}\n")

    for i, sess_info in enumerate(sessions, 1):
        # Format timestamp
        started_at = sess_info.get("started_at", 0)
        timestamp = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M:%S")

        # Status indicator
        status = sess_info.get("status", "unknown")
        status_colors = {
            "completed": GREEN,
            "failed": RED,
            "running": YELLOW,
            "interrupted": MAGENTA,
        }
        status_color = status_colors.get(status, DIM)
        status_str = f"{status_color}{status}{RESET}"

        # Step count
        step_count = sess_info.get("step_count", 0)

        # Stable short ID for reference (better than position-based numbering)
        short_id = sess_info.get("short_id", "")

        # Base commit (short hash)
        base_commit = sess_info.get("base_commit", "")
        commit_short = base_commit[:8] if base_commit else "n/a"

        # Prompt (truncated)
        prompt = sess_info.get("prompt", "")[:50]
        if len(sess_info.get("prompt", "")) > 50:
            prompt += "..."

        # Pipeline
        pipeline = sess_info.get("pipeline", "")[:40]

        # Show both recency number and stable short_id for reference
        print(f"  {CYAN}#{i}{RESET} ({YELLOW}{short_id}{RESET}) {DIM}{timestamp}{RESET}  [{status_str}]")
        print(f"     {BOLD}{prompt}{RESET}")
        print(f"     {DIM}pipeline:{RESET} {pipeline}")
        print(f"     {DIM}steps:{RESET} {step_count}  {DIM}base:{RESET} {commit_short}")
        print()

    print(f"{DIM}Reference sessions by number (#1) or stable ID ({YELLOW}abc12345{RESET}).{RESET}")
    print(f"{DIM}Use :session-detail <id> to see step-by-step commits.{RESET}")
    print(f"{DIM}Use :session-resume <id> --from <step> to resume from a step.{RESET}")
    print(f"{DIM}Use :session-prune to clean up old sessions.{RESET}")


def _resolve_session_ref(manager: SessionManager, ref: str) -> tuple:
    """Resolve a session reference to a Session object.

    Supports:
    - Recency numbers: "1", "2", "#3"
    - Stable short IDs: "abc12345"

    Args:
        manager: SessionManager instance
        ref: Session reference string

    Returns:
        Tuple of (Session or None, error_message or None)
    """
    # Strip leading # if present (allows "#1" syntax)
    if ref.startswith("#"):
        ref = ref[1:]

    # Try as a number first
    try:
        num = int(ref)
        if num >= 1:
            sessions_count = len(manager.list_sessions(limit=num + 1))
            if num > sessions_count:
                return None, f"Session #{num} not found. Only {sessions_count} session(s) available."
            sess = manager.get_session_by_number(num)
            if sess:
                return sess, None
            return None, f"Session #{num} not found."
    except ValueError:
        pass

    # Try as a short ID (8 hex chars)
    if len(ref) == 8:
        sess = manager.get_session_by_short_id(ref)
        if sess:
            return sess, None
        return None, f"Session with ID '{ref}' not found."

    # Try as a full session ID
    sess = manager.load_session(ref)
    if sess:
        return sess, None

    return None, f"Invalid session reference: '{ref}'. Use a number (#1) or short ID (abc12345)."


def cmd_session_detail(session: SessionState, args: list[str]) -> None:
    """Show detailed session info with step-by-step commit hashes."""
    if not args:
        print(f"{YELLOW}Usage: :session-detail <id>{RESET}")
        print(f"Use session number (#1, #2) or stable ID (abc12345).")
        print(f"Use {CYAN}:sessions{RESET} to see available sessions.")
        return

    manager = SessionManager()
    sess, error = _resolve_session_ref(manager, args[0])

    if error:
        print(f"{RED}{error}{RESET}")
        print(f"Use {CYAN}:sessions{RESET} to see available sessions.")
        return

    # Format timestamps
    started_at = datetime.fromtimestamp(sess.started_at).strftime("%Y-%m-%d %H:%M:%S")
    completed_at = (
        datetime.fromtimestamp(sess.completed_at).strftime("%Y-%m-%d %H:%M:%S")
        if sess.completed_at else "in progress"
    )

    # Status
    status_colors = {
        "completed": GREEN,
        "failed": RED,
        "running": YELLOW,
        "interrupted": MAGENTA,
    }
    status_color = status_colors.get(sess.status, DIM)

    print(f"\n{BOLD}Session {YELLOW}{sess.short_id}{RESET}{BOLD}: {sess.prompt[:60]}{RESET}")
    print(f"{DIM}{'=' * 70}{RESET}\n")

    print(f"  {DIM}ID:{RESET}        {sess.session_id}")
    print(f"  {DIM}Status:{RESET}    {status_color}{sess.status}{RESET}")
    print(f"  {DIM}Started:{RESET}   {started_at}")
    print(f"  {DIM}Completed:{RESET} {completed_at}")
    print(f"  {DIM}Pipeline:{RESET}  {sess.pipeline}")
    print(f"  {DIM}CWD:{RESET}       {sess.cwd}")
    print(f"  {DIM}Base:{RESET}      {sess.base_commit or 'n/a'}")
    print(f"  {DIM}Tokens:{RESET}    {sess.total_tokens:,}")

    if sess.error:
        print(f"  {RED}Error:{RESET}     {sess.error}")

    print(f"\n{BOLD}Steps:{RESET}\n")

    for step in sess.steps:
        # Step status indicator
        step_status_colors = {
            "completed": GREEN,
            "failed": RED,
            "running": YELLOW,
            "pending": DIM,
            "skipped": MAGENTA,
        }
        step_color = step_status_colors.get(step.status, DIM)

        # Duration
        duration_str = ""
        if step.duration:
            duration_str = f" ({step.duration:.1f}s)"

        # Commit hash
        commit_str = step.commit_hash[:8] if step.commit_hash else "no commit"

        print(f"  {CYAN}Step {step.step_number}{RESET}: {step.function_name}")
        print(f"    {DIM}status:{RESET} {step_color}{step.status}{RESET}{duration_str}")
        print(f"    {DIM}commit:{RESET} {commit_str}")

        if step.files_changed:
            files_preview = ", ".join(step.files_changed[:3])
            if len(step.files_changed) > 3:
                files_preview += f", +{len(step.files_changed) - 3} more"
            print(f"    {DIM}files:{RESET}  {files_preview}")

        if step.tokens_used:
            print(f"    {DIM}tokens:{RESET} {step.tokens_used:,}")

        if step.error:
            print(f"    {RED}error:{RESET}  {step.error[:60]}")

        print()

    print(f"{DIM}Use :session-resume {sess.short_id} --from <step> to resume from a specific step.{RESET}")


def cmd_session_resume(session: SessionState, args: list[str]) -> None:
    """Resume a session from a specific step.

    Creates a worktree from the commit hash at that step, or resets
    the current directory with --in-place.
    """
    if not args:
        print(f"{YELLOW}Usage: :session-resume <id> --from <step> [--in-place]{RESET}")
        print(f"\nResumes session from step <step>.")
        print(f"Use session number (#1) or stable ID (abc12345).")
        print(f"\nOptions:")
        print(f"  --from <step>   Step number to resume from (0 = base commit)")
        print(f"  --in-place      Reset current directory instead of creating worktree")
        print(f"\nExamples:")
        print(f"  {CYAN}:session-resume 1 --from 2{RESET}         Resume session #1 from step 2 (worktree)")
        print(f"  {CYAN}:session-resume abc123 --from 0{RESET}    Resume by ID from base commit")
        print(f"  {CYAN}:session-resume 1 --from 2 --in-place{RESET}  Reset current dir to step 2")
        return

    # Parse arguments
    session_ref = None
    from_step = None
    from_step_str = None
    in_place = False

    i = 0
    while i < len(args):
        if args[i] == "--from" and i + 1 < len(args):
            from_step_str = args[i + 1]
            i += 2
        elif args[i] == "--in-place":
            in_place = True
            i += 1
        elif args[i].startswith("--"):
            print(f"{RED}Unknown option: {args[i]}{RESET}")
            print(f"Valid options: --from <step>, --in-place")
            return
        else:
            if session_ref is None:
                session_ref = args[i]
            i += 1

    if session_ref is None:
        print(f"{RED}Please specify a session (number or ID).{RESET}")
        print(f"Example: {CYAN}:session-resume 1 --from 2{RESET}")
        return

    if from_step_str is None:
        print(f"{RED}Please specify --from <step>.{RESET}")
        print(f"Example: {CYAN}:session-resume {session_ref} --from 1{RESET}")
        return

    # Validate step number (allow 0 for base commit)
    try:
        from_step = int(from_step_str)
    except ValueError:
        print(f"{RED}Invalid step number: '{from_step_str}' is not a number.{RESET}")
        return

    if from_step < 0:
        print(f"{RED}Invalid step number: must be 0 or greater, got {from_step}.{RESET}")
        print(f"Use 0 to resume from the base commit (before any steps).")
        return

    manager = SessionManager()
    sess, error = _resolve_session_ref(manager, session_ref)

    if error:
        print(f"{RED}{error}{RESET}")
        print(f"Use {CYAN}:sessions{RESET} to see available sessions.")
        return

    # Validate step number against session
    if from_step > len(sess.steps):
        print(f"{RED}Step {from_step} not found in session.{RESET}")
        print(f"Session has {len(sess.steps)} step(s). Use step 0-{len(sess.steps)}.")
        return

    # Get commit hash for the step
    if from_step == 0:
        commit_hash = sess.base_commit
        if not commit_hash:
            print(f"{RED}Session has no base commit recorded.{RESET}")
            print(f"The session may have been run with auto_commit disabled.")
            return
    else:
        step = sess.get_step(from_step)
        commit_hash = step.commit_hash if step else None
        if not commit_hash:
            print(f"{RED}Step {from_step} has no commit hash recorded.{RESET}")
            print(f"To use resume, enable auto_commit in config: [session] auto_commit = true")
            return

    # Show what we're about to do
    print(f"\n{BOLD}Resume Session {YELLOW}{sess.short_id}{RESET}")
    print(f"{DIM}{'=' * 50}{RESET}\n")
    print(f"  Prompt:      {sess.prompt[:50]}")
    print(f"  From step:   {from_step}")
    print(f"  Commit:      {commit_hash[:12]}")
    print(f"  Mode:        {'in-place reset' if in_place else 'worktree'}")
    print()

    # List remaining steps
    remaining_steps = [s for s in sess.steps if s.step_number > from_step]
    if remaining_steps:
        print(f"{BOLD}Steps to re-run:{RESET}")
        for step in remaining_steps:
            print(f"  {step.step_number}. {step.function_name}")
        print()

    if in_place:
        # In-place reset of current directory
        _resume_in_place(sess, from_step, commit_hash)
    else:
        # Create worktree from commit
        _resume_with_worktree(sess, from_step, commit_hash)


def _resume_in_place(sess, from_step: int, commit_hash: str) -> None:
    """Reset current directory to a specific commit for resume.

    This is faster than creating a worktree but requires user confirmation
    as it may discard local changes.
    """
    import subprocess

    # Check for uncommitted changes
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=sess.cwd,
        capture_output=True,
        text=True,
    )

    if result.stdout.strip():
        print(f"{YELLOW}Warning: You have uncommitted changes.{RESET}")
        print(f"In-place reset will discard these changes:")
        for line in result.stdout.strip().split("\n")[:5]:
            print(f"  {line}")
        if len(result.stdout.strip().split("\n")) > 5:
            print(f"  ... and more")
        print()
        print(f"{RED}This action is destructive. Changes will be lost.{RESET}")
        print(f"To preserve changes, use worktree mode (without --in-place).")
        print()
        print(f"To proceed anyway, run: {CYAN}git reset --hard {commit_hash[:8]}{RESET}")
        return

    # Perform the reset
    try:
        result = subprocess.run(
            ["git", "reset", "--hard", commit_hash],
            cwd=sess.cwd,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(f"{GREEN}Reset to commit {commit_hash[:8]}{RESET}")
            print()
            print(f"{BOLD}To continue:{RESET}")
            print(f"  {CYAN}lion \"{sess.prompt}\"{RESET}")
        else:
            print(f"{RED}Failed to reset: {result.stderr}{RESET}")

    except Exception as e:
        print(f"{RED}Error during reset: {e}{RESET}")


def _resume_with_worktree(sess, from_step: int, commit_hash: str) -> None:
    """Create a worktree from commit for resume."""
    try:
        from ..worktree import WorktreeManager
        wt_manager = WorktreeManager(cwd=sess.cwd)
        worktree = wt_manager.reset_to_step(sess, from_step)

        if worktree:
            print(f"{GREEN}Created worktree at commit {commit_hash[:8]}:{RESET}")
            print(f"  Path:   {worktree.path}")
            print(f"  Branch: {worktree.branch}")
            print()
            print(f"{BOLD}To continue working:{RESET}")
            print(f"  1. {CYAN}cd {worktree.path}{RESET}")
            print(f"  2. {CYAN}lion \"{sess.prompt}\"{RESET}")
            print()
            print(f"{BOLD}When done:{RESET}")
            print(f"  - Merge changes: {CYAN}git merge {worktree.branch}{RESET} (from original repo)")
            print(f"  - Or cherry-pick: {CYAN}git cherry-pick <commits>{RESET}")
            print(f"  - Clean up: {CYAN}git worktree remove {worktree.path}{RESET}")
        else:
            print(f"{RED}Failed to create worktree.{RESET}")
            print(f"Make sure you're in a git repository and the commit {commit_hash[:8]} exists.")

    except Exception as e:
        print(f"{RED}Error creating worktree: {e}{RESET}")


def cmd_session_replay(session: SessionState, args: list[str]) -> None:
    """Replay a session (read-only display of what happened)."""
    if not args:
        print(f"{YELLOW}Usage: :session-replay <id>{RESET}")
        print(f"Replays session, showing each step's execution in sequence.")
        print(f"Use session number (#1) or stable ID (abc12345).")
        return

    manager = SessionManager()
    sess, error = _resolve_session_ref(manager, args[0])

    if error:
        print(f"{RED}{error}{RESET}")
        print(f"Use {CYAN}:sessions{RESET} to see available sessions.")
        return

    print(f"\n{BOLD}Replaying Session {YELLOW}{sess.short_id}{RESET}")
    print(f"{DIM}{'=' * 60}{RESET}\n")

    # Header
    started_at = datetime.fromtimestamp(sess.started_at).strftime("%Y-%m-%d %H:%M:%S")
    print(f"  {DIM}Prompt:{RESET}   {sess.prompt}")
    print(f"  {DIM}Pipeline:{RESET} {sess.pipeline}")
    print(f"  {DIM}Started:{RESET}  {started_at}")
    print(f"  {DIM}Base:{RESET}     {sess.base_commit[:12] if sess.base_commit else 'n/a'}")
    print()

    # Show each step as a timeline
    print(f"{BOLD}Execution Timeline:{RESET}\n")

    for step in sess.steps:
        # Step header
        status_symbols = {
            "completed": f"{GREEN}[OK]{RESET}",
            "failed": f"{RED}[FAIL]{RESET}",
            "running": f"{YELLOW}[...]{RESET}",
            "pending": f"{DIM}[--]{RESET}",
            "skipped": f"{MAGENTA}[SKIP]{RESET}",
        }
        status_sym = status_symbols.get(step.status, "[?]")

        duration_str = f" ({step.duration:.1f}s)" if step.duration else ""

        print(f"  {status_sym} {BOLD}Step {step.step_number}: {step.function_name}{RESET}{duration_str}")

        # Commit info
        if step.commit_hash:
            print(f"       {DIM}commit: {step.commit_hash[:12]}{RESET}")

        # Files changed
        if step.files_changed:
            print(f"       {DIM}files:{RESET}")
            for f in step.files_changed[:5]:
                print(f"         - {f}")
            if len(step.files_changed) > 5:
                print(f"         {DIM}... and {len(step.files_changed) - 5} more{RESET}")

        # Error if any
        if step.error:
            print(f"       {RED}error: {step.error[:80]}{RESET}")

        print()

    # Summary
    completed_steps = sum(1 for s in sess.steps if s.status == "completed")
    failed_steps = sum(1 for s in sess.steps if s.status == "failed")
    total_duration = sess.duration

    print(f"{DIM}{'=' * 60}{RESET}")
    print(f"\n{BOLD}Summary:{RESET}")
    print(f"  Steps: {completed_steps} completed, {failed_steps} failed, {len(sess.steps)} total")
    if total_duration:
        print(f"  Duration: {total_duration:.1f}s")
    print(f"  Tokens: {sess.total_tokens:,}")
    print(f"  Status: {sess.status}")
    print()


def cmd_session_prune(session: SessionState, args: list[str]) -> None:
    """Clean up old sessions based on count and age limits.

    Removes sessions beyond the maximum limit or older than the age limit.
    """
    # Parse arguments
    max_sessions = None
    max_age_days = None

    i = 0
    while i < len(args):
        if args[i] == "--keep" and i + 1 < len(args):
            max_sessions = _validate_positive_int(args[i + 1], "keep count", max_value=1000)
            if max_sessions is None:
                return
            i += 2
        elif args[i] == "--max-age" and i + 1 < len(args):
            max_age_days = _validate_positive_int(args[i + 1], "max age days", max_value=365)
            if max_age_days is None:
                return
            i += 2
        elif args[i].startswith("--"):
            print(f"{RED}Unknown option: {args[i]}{RESET}")
            print(f"Valid options: --keep <n>, --max-age <days>")
            return
        else:
            i += 1

    manager = SessionManager()

    # Show current state
    all_sessions = manager.list_sessions(limit=500)
    print(f"\n{BOLD}Session Cleanup{RESET}")
    print(f"{DIM}{'=' * 50}{RESET}\n")
    print(f"  Total sessions: {len(all_sessions)}")

    if max_sessions is None and max_age_days is None:
        # Show info and usage
        print(f"\n{DIM}No cleanup parameters specified. Showing current state.{RESET}")
        print(f"\n{BOLD}Usage:{RESET}")
        print(f"  {CYAN}:session-prune --keep 50{RESET}        Keep only 50 most recent sessions")
        print(f"  {CYAN}:session-prune --max-age 7{RESET}      Remove sessions older than 7 days")
        print(f"  {CYAN}:session-prune --keep 50 --max-age 30{RESET}  Both limits")
        return

    # Perform cleanup
    print(f"\n  Cleanup criteria:")
    if max_sessions is not None:
        print(f"    Keep max: {max_sessions} sessions")
    if max_age_days is not None:
        print(f"    Max age: {max_age_days} days")
    print()

    removed = manager.prune_sessions(
        max_sessions=max_sessions,
        max_age_days=max_age_days,
    )

    if removed > 0:
        print(f"{GREEN}Removed {removed} session(s).{RESET}")
        remaining = len(manager.list_sessions(limit=500))
        print(f"  Remaining: {remaining} session(s)")
    else:
        print(f"No sessions to remove.")


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
    # Status dashboard
    "dashboard": cmd_status_dashboard,
    "dash": cmd_status_dashboard,
    "quota": cmd_status_dashboard,
    # Session history commands
    "session-history": cmd_session_history,
    "sessions": cmd_session_history,
    "sh": cmd_session_history,
    "session-detail": cmd_session_detail,
    "sd": cmd_session_detail,
    "session-resume": cmd_session_resume,
    "sr": cmd_session_resume,
    "session-replay": cmd_session_replay,
    "splay": cmd_session_replay,
    "session-prune": cmd_session_prune,
    "sprune": cmd_session_prune,
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
    "dashboard": {
        "brief": "Show status dashboard",
        "detail": """Show the Lion status dashboard with quota usage, today's sessions, and active pipelines.

The dashboard displays:
- Quota usage per model with daily limits and warnings
- Today's pipeline runs with token usage and status
- Currently active (running) pipelines

By default, reads from ~/.lion (global data) to ensure consistent behavior
across directories. Use --local to view project-specific data instead.

Flags:
  --json, -j   Output machine-readable JSON instead of formatted tables
  --local, -l  Show data from current project's .lion directory instead of global

The dashboard reads data from:
- ~/.lion/quota.json for quota tracking
- ~/.lion/runs/ for session history
- ~/.lion/active/ for running pipelines

Note: Quota tracking is per-machine. Running Lion from multiple machines
(laptop, desktop, CI) will track usage separately on each machine.

Aliases: :dash, :quota""",
        "examples": [
            ":dashboard",
            ":dash",
            ":quota",
            ":dashboard --json",
            ":dashboard --local",
        ],
    },
    "session-history": {
        "brief": "Show pipeline session history with commit hashes",
        "detail": """Show recent pipeline sessions from ~/.lion/sessions/.

Each session tracks:
  - The original prompt and pipeline
  - Git commit hashes at each step
  - Status (completed, failed, running, interrupted)
  - Token usage and timing

Sessions can be referenced by:
  - Recency number: #1, #2, #3 (1 = most recent)
  - Stable short ID: abc12345 (8-char hex, never changes)

Aliases: :sessions, :sh""",
        "examples": [
            ":session-history",
            ":sessions",
            ":sh 20",
        ],
    },
    "session-detail": {
        "brief": "Show detailed session with step commits",
        "detail": """Show detailed information about a specific session.

Displays:
  - Session metadata (prompt, pipeline, cwd, timestamps)
  - Each step with its commit hash
  - Files changed at each step
  - Token usage and errors

Reference sessions by number (#1) or stable ID (abc12345).

Aliases: :sd""",
        "examples": [
            ":session-detail 1",
            ":session-detail abc12345",
            ":sd 3",
        ],
    },
    "session-resume": {
        "brief": "Resume session from a specific step",
        "detail": """Resume a session from a specific step.

Two modes available:
  - Worktree (default): Creates a new worktree, preserves current state
  - In-place (--in-place): Resets current directory to the commit

Use --from 0 to start from the base commit (before any steps).

Reference sessions by number (#1) or stable ID (abc12345).

Worktree workflow:
  1. Run :session-resume <id> --from <step> to create the worktree
  2. cd into the worktree path shown
  3. Run lion with your prompt to continue
  4. When done, merge changes back: git merge <branch>
  5. Clean up: git worktree remove <path>

In-place workflow:
  1. Run :session-resume <id> --from <step> --in-place
  2. Run lion with your prompt to continue

Aliases: :sr""",
        "examples": [
            ":session-resume 1 --from 2",
            ":session-resume abc12345 --from 0",
            ":sr 1 --from 2 --in-place",
        ],
    },
    "session-replay": {
        "brief": "Replay a session (read-only)",
        "detail": """Replay a session showing what happened at each step.

This is a read-only view of the session execution timeline,
showing status, commits, files changed, and errors for each step.

Reference sessions by number (#1) or stable ID (abc12345).

Aliases: :splay""",
        "examples": [
            ":session-replay 1",
            ":session-replay abc12345",
            ":splay 3",
        ],
    },
    "session-prune": {
        "brief": "Clean up old sessions",
        "detail": """Remove old sessions based on count and/or age limits.

Options:
  --keep <n>      Keep only the N most recent sessions
  --max-age <d>   Remove sessions older than D days

Without options, shows current session count and usage.

Sessions are stored in ~/.lion/sessions/ and can accumulate over time.
Use this command periodically to clean up old sessions.

Aliases: :sprune""",
        "examples": [
            ":session-prune",
            ":session-prune --keep 50",
            ":session-prune --max-age 7",
            ":session-prune --keep 100 --max-age 30",
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
