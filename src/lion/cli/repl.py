"""REPL controller for LionCLI.

Provides the interactive read-eval-print loop with readline support,
command parsing, and pipeline execution.
"""

import argparse
import atexit
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# readline is optional (not available on Windows by default)
try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False
    readline = None  # type: ignore

from .session import SessionState
from .commands import handle_command, COMMANDS, cmd_cycle_verbosity, cmd_context_toggle
from .views import ViewRenderer
from .autocomplete import get_pipeline_completions_for_readline, highlight_pipeline


# Special escape sequences for keyboard shortcuts in interactive mode
# These are inserted by readline key bindings and detected in the REPL loop
CTRL_L_SEQUENCE = "\x0c"  # Ctrl+L (form feed)
CTRL_T_SEQUENCE = "\x14"  # Ctrl+T
from ..display import Display, GREEN, YELLOW, RED, BLUE, CYAN, DIM, BOLD, RESET, LION
from ..lenses import get_lens
from ..parser import parse_lion_input
from ..pipeline import PipelineExecutor
from ..memory import SharedMemory


# Config file locations (same as lion.py)
def _find_lion_dir():
    """Find the lion package directory."""
    return Path(__file__).parent.parent.parent.parent


def load_config():
    """Load config from config.toml if it exists.

    Returns:
        Tuple of (config_dict, config_path or None)
    """
    lion_dir = _find_lion_dir()

    for config_path in [
        lion_dir / "config.toml",
        lion_dir / "config.default.toml",
        Path.home() / ".lion" / "config.toml",
    ]:
        if config_path.exists():
            try:
                import tomllib
                with open(config_path, "rb") as f:
                    return tomllib.load(f), config_path
            except Exception:
                pass
    return {}, None


def validate_pipeline(input_str: str, config: dict) -> tuple[bool, str, str, list]:
    """Validate and parse pipeline input.

    Args:
        input_str: The raw pipeline input
        config: Config dict for parsing

    Returns:
        Tuple of (valid, error_message, prompt, steps)
    """
    from .autocomplete import _get_available_functions

    # Basic validation before parsing
    input_str = input_str.strip()

    if not input_str:
        return False, "Empty input", "", []

    # Check for unclosed quotes with position info
    quote_char = None
    quote_pos = 0
    for i, char in enumerate(input_str):
        if char in ('"', "'"):
            if quote_char is None:
                quote_char = char
                quote_pos = i
            elif char == quote_char:
                quote_char = None

    if quote_char:
        # Show context around the unclosed quote
        context_start = max(0, quote_pos - 5)
        context_end = min(len(input_str), quote_pos + 15)
        context = input_str[context_start:context_end]
        marker = " " * (quote_pos - context_start) + "^"
        return False, f"Unclosed {quote_char} quote at position {quote_pos + 1}:\n  {context}\n  {marker}", "", []

    # Check for unclosed parentheses with position info
    paren_count = 0
    open_positions = []
    for i, char in enumerate(input_str):
        if char == "(":
            paren_count += 1
            open_positions.append(i)
        elif char == ")":
            if paren_count <= 0:
                # Show context around the unmatched close paren
                context_start = max(0, i - 10)
                context_end = min(len(input_str), i + 5)
                context = input_str[context_start:context_end]
                marker = " " * (i - context_start) + "^"
                return False, f"Unmatched ')' at position {i + 1}:\n  {context}\n  {marker}", "", []
            paren_count -= 1
            open_positions.pop()

    if paren_count > 0:
        # Show the first unclosed paren
        pos = open_positions[0]
        context_start = max(0, pos - 5)
        context_end = min(len(input_str), pos + 20)
        context = input_str[context_start:context_end]
        marker = " " * (pos - context_start) + "^"
        return False, f"Unclosed '(' at position {pos + 1} ({paren_count} unclosed):\n  {context}\n  {marker}", "", []

    # Try to parse
    try:
        prompt, steps = parse_lion_input(input_str, config)
        if not prompt:
            # Give a hint about expected format
            return False, "Could not extract prompt. Expected: \"your prompt\" -> function()", "", []

        # Validate function names
        available_funcs = set(_get_available_functions())
        for step in steps:
            if step.function != "__pattern__" and step.function not in available_funcs:
                similar = [f for f in available_funcs if f.startswith(step.function[:2])]
                hint = f" Did you mean: {', '.join(similar[:3])}?" if similar else ""
                return False, f"Unknown function '{step.function}'.{hint}\nAvailable: {', '.join(sorted(available_funcs)[:10])}...", "", []

        return True, "", prompt, steps
    except Exception as e:
        error_msg = str(e)
        # Try to provide more context for common errors
        if "invalid syntax" in error_msg.lower():
            return False, f"Syntax error: {error_msg}\nExpected format: \"prompt\" -> function() -> function()", "", []
        return False, f"Parse error: {error_msg}", "", []


def _should_use_tui(steps) -> bool:
    """Decide whether to launch the Textual TUI for this pipeline."""
    if not sys.stdout.isatty():
        return False
    try:
        from .tui import LionApp  # noqa: F401
        return len(steps) > 0
    except ImportError:
        return False


def execute_pipeline(session: SessionState, input_str: str) -> None:
    """Execute a pipeline from user input.

    Args:
        session: Current session state
        input_str: The pipeline input
    """
    # Validate input
    valid, error, prompt, steps = validate_pipeline(input_str, session.config)

    if not valid:
        print(f"{RED}Error: {error}{RESET}")
        return

    # Show highlighted pipeline
    if steps:
        print(f"{DIM}Pipeline: {highlight_pipeline(input_str)}{RESET}")

    # Create run directory
    run_id = (
        time.strftime("%Y-%m-%d_%H%M%S")
        + "_"
        + prompt[:30].replace(" ", "_").replace("/", "_")
    )
    run_dir = session.cwd / ".lion" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Configure context mode based on reason_mode
    config = dict(session.config)
    if session.reason_mode == "off":
        config["context_mode"] = "minimal"
    elif session.reason_mode == "on":
        config["context_mode"] = "standard"
    elif session.reason_mode == "full":
        config["context_mode"] = "rich"

    # Apply active lens if set
    if session.current_lens:
        # Inject lens into the first applicable step
        lens = get_lens(session.current_lens)
        if lens:
            config["_active_lens"] = lens
            print(f"{DIM}Applying lens: {lens.name} ({lens.shortcode}){RESET}")

    # Create executor
    executor = PipelineExecutor(
        prompt=prompt,
        steps=steps,
        config=config,
        run_dir=str(run_dir),
        cwd=str(session.cwd),
    )

    # Launch TUI if available and interactive
    if _should_use_tui(steps) and getattr(session, "tui_mode", True):
        _run_with_tui(session, prompt, steps, config, run_dir, executor, input_str)
        return

    # Fallback: line-based output (batch mode or no textual)
    _run_line_mode(session, executor, run_dir, input_str)


def _run_with_tui(session, prompt, steps, config, run_dir, executor, input_str):
    """Launch the Textual TUI for pipeline execution."""
    from .tui import LionApp

    app = LionApp(
        prompt=prompt,
        steps=steps,
        config=config,
        run_dir=str(run_dir),
        executor=lambda: executor.run(),
    )

    try:
        app.run()
    except Exception as e:
        if session.debug_mode:
            traceback.print_exc()
        else:
            print(f"{RED}TUI error: {e}{RESET}")
            print(f"{DIM}Falling back to line mode...{RESET}")
            _run_line_mode(session, executor, run_dir, input_str)
            return

    # Load the run into session for inspection after TUI exits
    session.load_run(run_dir)
    session.history.append(input_str)


def _run_line_mode(session, executor, run_dir, input_str):
    """Execute pipeline with line-based output (original behavior)."""
    try:
        result = executor.run()

        # Show result
        if result.content:
            Display.agent_result(result.content)

        Display.final_result(result, str(run_dir))

        # Load the run into session for inspection
        session.load_run(run_dir)
        session.history.append(input_str)

        # Show hint about inspection
        if session.reason_mode != "off" and session.memory:
            entries_with_reasoning = sum(
                1 for e in session.memory.read_all() if e.reasoning
            )
            if entries_with_reasoning > 0:
                print(
                    f"{DIM}Tip: {entries_with_reasoning} entries have reasoning data. "
                    f"Use :inspect to explore.{RESET}"
                )

    except KeyboardInterrupt:
        Display.cancelled()
    except Exception as e:
        if session.debug_mode:
            traceback.print_exc()
        else:
            print(f"{RED}Error: {str(e)}{RESET}")
            print(f"{DIM}Use :debug on for full traceback.{RESET}")


def _is_fuzzy_match(query: str, candidate: str) -> bool:
    """Check if query characters appear in order within candidate."""
    if not query:
        return True

    it = iter(candidate)
    return all(ch in it for ch in query)


def get_command_completions(text: str) -> list[str]:
    """Return command completion candidates for readline."""
    if not text.startswith(":"):
        return []

    cmd_prefix = text[1:].lower()
    all_commands = sorted(set(COMMANDS.keys()))
    prefixed = [f":{cmd}" for cmd in all_commands if cmd.startswith(cmd_prefix)]
    prefixed_set = {m[1:] for m in prefixed}

    # Keep prefix matches first; add fuzzy matches as fallback.
    fuzzy = [f":{cmd}" for cmd in all_commands if cmd not in prefixed_set and _is_fuzzy_match(cmd_prefix, cmd)]
    return prefixed + fuzzy


def setup_readline():
    """Configure readline for command history and completion."""
    if not HAS_READLINE:
        return

    # Set up history file
    history_file = Path.home() / ".lion" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        readline.read_history_file(str(history_file))
    except FileNotFoundError:
        pass

    # Save history on exit with error handling
    def save_history():
        try:
            readline.write_history_file(str(history_file))
        except OSError:
            pass  # Best effort on exit

    atexit.register(save_history)

    # Set history length
    readline.set_history_length(1000)

    # Combined completion for :commands and pipeline syntax
    _completion_cache = {"text": None, "matches": []}

    def completer(text, state):
        # Cache completions for the same text (readline calls multiple times)
        line_buffer = readline.get_line_buffer() if readline else text

        if _completion_cache["text"] != line_buffer:
            _completion_cache["text"] = line_buffer

            # Determine what to complete based on context
            if line_buffer.lstrip().startswith(":"):
                # Command completion
                _completion_cache["matches"] = get_command_completions(line_buffer)
            else:
                # Pipeline completion - returns text to replace readline's `text` word
                _completion_cache["matches"] = get_pipeline_completions_for_readline(
                    line_buffer, text
                )

        matches = _completion_cache["matches"]
        if state < len(matches):
            return matches[state]
        return None

    readline.set_completer(completer)
    # Use complete for tab, allow partial word completion
    readline.parse_and_bind("tab: complete")
    # Delimiters include parens and comma so readline words align with tokens
    readline.set_completer_delims(" \t\n;(),")  # space, tab, newline, semicolon, parens, comma


def setup_interactive_keybindings():
    """Set up readline key bindings for interactive mode.

    Binds Ctrl+L and Ctrl+T to insert special sequences that are
    detected in the REPL loop and translated to commands.
    """
    if not HAS_READLINE:
        return

    # Ctrl+L: Insert a special marker that means "cycle verbosity"
    # We use quoted-insert to insert the literal control character
    # The REPL loop will detect this and execute the command
    try:
        # Bind Ctrl+L to insert the form feed character (^L)
        # This will be detected in the input and trigger cmd_cycle_verbosity
        readline.parse_and_bind('"\\C-l": "\\C-l"')

        # Bind Ctrl+T to insert the DC4 character (^T)
        # This will be detected in the input and trigger cmd_context_toggle
        readline.parse_and_bind('"\\C-t": "\\C-t"')
    except Exception:
        # Silently ignore if bindings fail (e.g., on Windows)
        pass


def clear_interactive_keybindings():
    """Clear the interactive mode key bindings.

    Restores default behavior for Ctrl+L and Ctrl+T.
    """
    if not HAS_READLINE:
        return

    try:
        # Restore Ctrl+L to default (clear screen in some terminals)
        readline.parse_and_bind('"\\C-l": clear-screen')
        # Restore Ctrl+T to default (transpose characters)
        readline.parse_and_bind('"\\C-t": transpose-chars')
    except Exception:
        pass


def handle_interactive_input(session: SessionState, line: str) -> tuple[bool, str]:
    """Process input for interactive mode keyboard shortcuts.

    Detects special control characters inserted by readline bindings
    and translates them to command execution.

    Args:
        session: Current session state
        line: Raw input line

    Returns:
        Tuple of (was_handled, remaining_line)
        If was_handled is True, the input was a keyboard shortcut and was executed.
        remaining_line is the input with any control characters stripped.
    """
    if not session.interactive_mode:
        return False, line

    # Check for Ctrl+L (cycle verbosity)
    if CTRL_L_SEQUENCE in line:
        # Execute the cycle verbosity command
        cmd_cycle_verbosity(session, [])
        # Remove the control character and return remaining input
        remaining = line.replace(CTRL_L_SEQUENCE, "").strip()
        if not remaining:
            return True, ""
        return True, remaining

    # Check for Ctrl+T (context toggle)
    if CTRL_T_SEQUENCE in line:
        # Execute the context toggle command
        cmd_context_toggle(session, [])
        # Remove the control character and return remaining input
        remaining = line.replace(CTRL_T_SEQUENCE, "").strip()
        if not remaining:
            return True, ""
        return True, remaining

    return False, line


def build_prompt(session: SessionState) -> str:
    """Build the REPL prompt based on session state and prompt style.

    Args:
        session: Current session state

    Returns:
        Formatted prompt string
    """
    if session.prompt_style == "enriched":
        # Build enriched prompt: lion [lens|reason|N]>
        parts = []

        # Lens (if set)
        if session.current_lens:
            parts.append(session.current_lens)
        else:
            parts.append("-")

        # Reason mode
        parts.append(session.reason_mode)

        # Entry count
        if session.has_run():
            count = session.memory.count()
            parts.append(str(count))
        else:
            parts.append("-")

        status = "|".join(parts)

        if session.has_run():
            run_id = session.get_run_id()[:15]
            return f"{CYAN}{run_id}{RESET} lion [{DIM}{status}{RESET}]> "
        else:
            return f"lion [{DIM}{status}{RESET}]> "
    else:
        # Default prompt
        if session.has_run():
            run_id = session.get_run_id()[:20]
            return f"{CYAN}{run_id}{RESET} lion> "
        else:
            return "lion> "


def print_banner(session: SessionState):
    """Print the startup banner."""
    lion_art = rf'''{YELLOW}
                      ,.
                   ,_> `.   ,';
               ,-`'      `'   '`'._
            ,,-) ---._   |   .---''`-),.
          ,'      `.  \  ;  /   _,'     `,
       ,--' ____       \   '  ,'    ___  `-,
      _>   /--. `-.              .-'.--\   \__
     '-,  (    `.  `.,`~ \~'-. ,' ,'    )    _\
     _<    \     \ ,'  ') )   `. /     /    <,.
  ,-'   _,  \    ,'    ( /      `.    /        `-,
  `-.,-'     `.,'       `         `.,'  `\    ,-'
   ,'       _  /   ,,,      ,,,     \     `-. `-._
  /-,     ,'  ;   ' _ \    / _ `     ; `.     `(`-\
   /-,        ;    (o)      (o)      ;          `'`,
 ,~-'  ,-'    \     '        `      /     \      <_
 /-. ,'        \                   /       \     ,-'
   '`,     ,'   `-/             \-' `.      `-. <
    /_    /      /   (_     _)   \    \          `,
      `-._;  ,' |  .::.`-.-' :..  |       `-.    _\
        _/       \  `:: ,^. :.:' / `.        \,-'
      '`.   ,-'  /`-..-'-.-`-..-'\            `-.
        >_ /     ;  (\/( ' )\/)  ;     `-.    _<
        ,-'      `.  \`-^^^-'/  ,'        \ _<
         `-,  ,'   `. `"""""' ,'   `-.   <`'
           ')        `._.,,_.'        \ ,-'
            '._        '`'`'   \       <
               >   ,'       ,   `-.   <`'
                `,/          \      ,-`
                 `,   ,' |   /     /
                  '; /   ;        (
                   _)|   `       (
                   `')         .-'
                     <_   \   /
                       \   /\(
                        `;/  `
{RESET}'''
    print()
    print(lion_art.rstrip())
    print(f"{LION} {BOLD}LionCLI{RESET} - Interactive Reasoning Explorer")
    print(f"{DIM}{'=' * 58}{RESET}")

    if session.config_path:
        print(f"Config:   {CYAN}{session.config_path}{RESET}")
    else:
        print(f"Config:   {DIM}(defaults){RESET}")

    provider = session.config.get("providers", {}).get("default", "claude")
    print(f"Provider: {provider}")

    context_mode = session.config.get("context", {}).get("default_mode", "auto")
    print(f"Context:  {context_mode}")

    print()
    print(f"Type a prompt to execute a pipeline, or use {CYAN}:help{RESET} for commands.")
    print(f"Quick toggles: {CYAN}:cv{RESET} (verbosity) | {CYAN}:ct{RESET} (expand/collapse)")
    print(f"Enable keyboard shortcuts with {CYAN}:interactive on{RESET}")
    print(f"Use {CYAN}:quit{RESET} or Ctrl+D to exit.")
    print()


def main():
    """Main entry point for LionCLI."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="LionCLI - Interactive Reasoning Explorer for Lion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  lioncli              Start interactive session
  lioncli --debug      Start with debug mode enabled

In the REPL:
  "Build a feature" -> pride(3)     Execute a pipeline
  :inspect                          Inspect current run
  :history                          Show recent runs
  :help                             Show all commands
""",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Start with debug mode enabled (full tracebacks)",
    )

    parser.add_argument(
        "-cs", "--context-short",
        action="store_true",
        dest="context_short",
        help="Show condensed context summary and exit",
    )

    parser.add_argument(
        "--context-level",
        choices=["minimal", "normal", "full"],
        default=None,
        help="Context display verbosity: minimal (tokens only), normal (default), full (with previews)",
    )

    args = parser.parse_args()

    # Prevent recursive lion calls
    if os.environ.get("LION_NO_RECURSE"):
        print("LionCLI: recursive call blocked (called from within a Lion agent)")
        sys.exit(0)

    # Set recursion guard
    os.environ["LION_NO_RECURSE"] = "1"

    # Load config
    config, config_path = load_config()

    # Handle --context-short flag (non-interactive mode)
    if args.context_short:
        runs_dir = Path.cwd() / ".lion" / "runs"
        if not runs_dir.exists():
            print("Context: no runs found")
            sys.exit(0)

        # Find latest run
        runs = []
        try:
            for run_dir in runs_dir.iterdir():
                if run_dir.is_dir() and (run_dir / "memory.jsonl").exists():
                    mtime = (run_dir / "memory.jsonl").stat().st_mtime
                    runs.append((run_dir, mtime))
        except PermissionError:
            print("Context: permission denied")
            sys.exit(1)

        if not runs:
            print("Context: no runs found")
            sys.exit(0)

        # Load the latest run
        runs.sort(key=lambda x: x[1], reverse=True)
        latest_run_dir = runs[0][0]

        try:
            memory = SharedMemory.load(latest_run_dir)
            entries = memory.read_all()
            total_chars = sum(len(e.content) for e in entries)
            print(ViewRenderer.render_context_short(len(entries), total_chars, True))
        except Exception:
            print("Context: error loading run")
            sys.exit(1)

        sys.exit(0)

    # Load context_level from config if not specified on command line
    context_level = args.context_level
    if context_level is None:
        # Try to load from config
        cli_config = config.get("cli", {})
        context_level = cli_config.get("context_level", "normal")
        # Validate config value
        if context_level not in ("minimal", "normal", "full"):
            print(f"Warning: Invalid context_level '{context_level}' in config, using 'normal'")
            context_level = "normal"

    # Create session
    session = SessionState(
        config=config,
        config_path=config_path,
        debug_mode=args.debug,
        cwd=Path.cwd(),
        context_level=context_level,
    )

    # Setup readline
    setup_readline()

    # Print banner
    print_banner(session)

    # Track interactive mode state for keybinding setup
    interactive_mode_active = False

    # REPL loop
    while True:
        try:
            # Set up or clear interactive keybindings based on mode
            if session.interactive_mode and not interactive_mode_active:
                setup_interactive_keybindings()
                interactive_mode_active = True
            elif not session.interactive_mode and interactive_mode_active:
                clear_interactive_keybindings()
                interactive_mode_active = False

            # Build prompt based on style
            prompt_str = build_prompt(session)

            line = input(prompt_str).strip()

            if not line:
                continue

            # Redraw the line with syntax highlighting (colored arrows, functions, etc.)
            if "->" in line and not line.startswith(":"):
                colored = highlight_pipeline(line)
                # Move cursor up one line, clear it, and reprint with colors
                sys.stdout.write(f"\033[A\r\033[K{prompt_str}{colored}\n")
                sys.stdout.flush()

            # Handle interactive mode keyboard shortcuts
            if session.interactive_mode:
                was_handled, remaining = handle_interactive_input(session, line)
                if was_handled:
                    if not remaining:
                        continue
                    line = remaining

            # Handle commands (start with :)
            if line.startswith(":"):
                handle_command(session, line)
            else:
                # Execute as pipeline
                execute_pipeline(session, line)

        except KeyboardInterrupt:
            print(f"\n{DIM}Use :quit to exit.{RESET}")

        except EOFError:
            # Ctrl+D
            print(f"\n{YELLOW}Goodbye!{RESET}")
            break

        except Exception as e:
            if session.debug_mode:
                traceback.print_exc()
            else:
                print(f"{RED}Error: {str(e)}{RESET}")


if __name__ == "__main__":
    main()
