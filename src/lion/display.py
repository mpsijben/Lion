"""Terminal output formatting for Lion."""

import sys
import threading

# ANSI colors
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
CYAN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
LION = f"{YELLOW}\U0001f981{RESET}"

# Thread-local storage for subtask context
_task_context = threading.local()


def _get_task_prefix():
    """Get the current subtask prefix for display, if any."""
    label = getattr(_task_context, "label", None)
    if label:
        return f"{CYAN}[{label}]{RESET} "
    return ""


def _print(msg):
    """Print to terminal, bypassing any stdout redirection."""
    prefix = _get_task_prefix()
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(prefix + msg + "\n")
            tty.flush()
    except OSError:
        print(prefix + msg, file=sys.stderr)


_PREAMBLE_STARTS = (
    "perfect.", "perfect,", "perfect!", "perfect -",
    "great.", "great,", "great!", "great -",
    "excellent.", "excellent,", "excellent!",
    "understood.", "understood,", "understood!",
    "okay,", "okay.", "ok,", "ok.",
    "sure,", "sure.", "absolutely.", "absolutely,",
    "alright,", "alright.",
    "thank you", "thanks for",
    "now i have", "i have analyzed", "i have a complete",
    "i have a comprehensive", "i've analyzed", "i've reviewed",
    "i now have", "i understand", "i'll analyze", "i will analyze",
    "i can see", "looking at",
    "let me ", "here's my ", "here is my ",
    "after analyzing", "after reviewing",
    "based on my analysis", "based on my review",
    "i'll provide", "i will provide",
)


def _skip_preamble(text):
    """Strip boilerplate preamble lines from AI output for display."""
    lines = text.strip().split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(lower.startswith(p) for p in _PREAMBLE_STARTS):
            continue
        # Found a non-preamble line, return from here
        return "\n".join(lines[i:])
    return text


class Display:

    @staticmethod
    def set_task_label(label):
        """Set a subtask label that prefixes all output lines.

        Use None to clear the label.
        """
        _task_context.label = label

    @staticmethod
    def pipeline_start(prompt, steps):
        _print(f"\n{LION} Lion starting...")
        _print(f"   {BOLD}Prompt:{RESET} {prompt}")
        if steps:
            parts = []
            for i, s in enumerate(steps):
                step_str = f"{s.function}({', '.join(str(a) for a in s.args)})"
                if i > 0:
                    if s.feedback:
                        if s.feedback_agents is not None:
                            op = f" <{s.feedback_agents}-> "
                        else:
                            op = " <-> "
                    else:
                        op = " -> "
                    parts.append(op)
                parts.append(step_str)
            _print(f"   {BOLD}Pipeline:{RESET} {''.join(parts)}")
        _print("")

    @staticmethod
    def auto_pipeline(complexity, pipeline):
        _print(f"   {DIM}Complexity: {complexity} -> auto pipeline: {pipeline}{RESET}")

    @staticmethod
    def pride_start(n, models):
        model_str = ", ".join(models)
        _print(f"   {BLUE}> Starting pride of {n} ({model_str}){RESET}")

    @staticmethod
    def phase(name, description):
        icons = {
            "propose": "\U0001f4ad",    # speech balloon
            "critique": "\U0001f50d",   # magnifying glass
            "converge": "\U0001f3af",   # target
            "implement": "\U0001f528",  # hammer
            "review": "\U0001f4dd",     # memo
            "test": "\U0001f9ea",       # test tube
            "pr": "\U0001f680",         # rocket
            "refine": "\U0001f504",     # counterclockwise arrows (feedback loop)
        }
        icon = icons.get(name, ">")
        _print(f"\n   {icon} {BOLD}{name.upper()}{RESET}: {description}")

    @staticmethod
    def agent_proposal(num, model, preview, lens=None):
        preview_clean = _skip_preamble(preview).replace("\n", " ")[:150]
        lens_label = f"::{lens.shortcode}" if lens else ""
        _print(f"   +-- Agent {num} ({model}{lens_label}): {DIM}{preview_clean}...{RESET}")

    @staticmethod
    def agent_critique(num, preview, lens=None):
        preview_clean = _skip_preamble(preview).replace("\n", " ")[:150]
        lens_label = f" [{lens.name}]" if lens else ""
        _print(f"   |-- Agent {num}{lens_label} critique: {DIM}{preview_clean}...{RESET}")

    @staticmethod
    def convergence(preview):
        preview_clean = preview.replace("\n", " ")[:300]
        _print(f"   +-- {GREEN}Consensus:{RESET} {DIM}{preview_clean}...{RESET}")

    @staticmethod
    def step_start(num, total, step):
        args_str = ", ".join(str(a) for a in step.args) if step.args else ""
        _print(f"\n   [{num}/{total}] {BOLD}{step.function}({args_str}){RESET}")

    @staticmethod
    def step_complete(func_name, result):
        _print(f"   {GREEN}v{RESET} {func_name} complete")

    @staticmethod
    def step_summary(func_name, result):
        """Show a brief summary of a step's output."""
        # Show issue counts for review/devil/lint/typecheck
        critical = result.get("critical_count", 0)
        warning = result.get("warning_count", 0)
        suggestion = result.get("suggestion_count", 0)

        if critical or warning or suggestion:
            parts = []
            if critical:
                parts.append(f"{RED}{critical} critical{RESET}")
            if warning:
                parts.append(f"{YELLOW}{warning} warnings{RESET}")
            if suggestion:
                parts.append(f"{DIM}{suggestion} suggestions{RESET}")
            _print(f"   Issues: {', '.join(parts)}")

        # Show content preview (first 3 meaningful lines)
        content = result.get("content", "")
        if content:
            lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            preview_lines = lines[:3]
            for line in preview_lines:
                _print(f"   {DIM}{line[:120]}{RESET}")
            if len(lines) > 3:
                _print(f"   {DIM}... ({len(lines) - 3} more lines){RESET}")

    @staticmethod
    def step_error(func_name, error):
        _print(f"   {RED}x{RESET} {func_name} failed: {error}")

    @staticmethod
    def agent_result(content):
        """Show the agent's response content."""
        if not content:
            return
        _print(f"\n   {BOLD}Result:{RESET}")
        for line in content.strip().split("\n"):
            _print(f"   {line}")

    @staticmethod
    def final_result(result, run_dir=None):
        _print(f"\n{'=' * 50}")
        if result.success:
            _print(f"{LION} {GREEN}Done!{RESET}")
        else:
            _print(f"{LION} {YELLOW}Completed with errors{RESET}")

        _print(f"   Steps: {result.steps_completed}/{result.total_steps}")
        _print(f"   Duration: {result.total_duration:.1f}s")

        # Show agent summaries from pride
        if result.agent_summaries:
            _print(f"\n   {BOLD}Agents:{RESET}")
            for a in result.agent_summaries:
                name = a.get("agent", "?").replace("agent_", "Agent ")
                lens = a.get("lens")
                lens_name = a.get("lens_name")
                if lens and lens_name:
                    lens_label = f" {CYAN}[{lens}: {lens_name}]{RESET}"
                elif lens:
                    lens_label = f" {CYAN}[{lens}]{RESET}"
                else:
                    lens_label = ""
                summary = a.get("summary", "")
                _print(f"   - {name}{lens_label}: {DIM}{summary}{RESET}")

        # Show the decision
        if result.final_decision:
            _print(f"\n   {BOLD}Decision:{RESET} {result.final_decision}")

        if result.files_changed:
            _print(f"\n   {BOLD}Files changed:{RESET}")
            for f in result.files_changed:
                _print(f"   - {f}")

        if result.errors:
            _print(f"\n   {RED}Errors:{RESET}")
            for e in result.errors:
                _print(f"     - {e}")

        # Show run directory for full details
        if run_dir:
            import os
            # Show relative path if inside cwd
            cwd = os.getcwd()
            if run_dir.startswith(cwd):
                rel = os.path.relpath(run_dir, cwd)
            else:
                rel = run_dir
            _print(f"\n   {DIM}Full log: {rel}/memory.jsonl{RESET}")

        _print("")

    @staticmethod
    def cancelled():
        _print(f"\n{LION} Cancelled by user.")

    @staticmethod
    def error(message):
        _print(f"\n{LION} {RED}Error:{RESET} {message}")

    @staticmethod
    def notify(message):
        """Display a notification message."""
        _print(f"   {DIM}{message}{RESET}")

    @staticmethod
    def format_completion_summary(agent_summaries, final_decision, success=True, content=None):
        """Format a completion summary for the hook to return."""
        lines = []

        if success:
            lines.append("Lion voltooid!")
        else:
            lines.append("Lion voltooid met fouten")

        # Add agent summaries
        if agent_summaries:
            for agent_info in agent_summaries:
                agent_num = agent_info.get("agent", "agent_1").replace("agent_", "Agent ")
                summary = agent_info.get("summary", "Completed")
                lines.append(f"  - {agent_num}: {summary}")
        elif content:
            # Single agent - extract one-liner from content
            one_liner = content.strip().split("\n")[0][:150]
            lines.append(f"  - {one_liner}")
        else:
            lines.append("  - Taak uitgevoerd")

        if final_decision:
            lines.append(f"  > Beslissing: {final_decision}")

        return "\n".join(lines)
