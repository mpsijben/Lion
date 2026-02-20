"""Terminal output formatting for Lion."""

import sys

# ANSI colors
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
LION = f"{YELLOW}\U0001f981{RESET}"


def _print(msg):
    """Print to terminal, bypassing any stdout redirection."""
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(msg + "\n")
            tty.flush()
    except OSError:
        print(msg, file=sys.stderr)


class Display:

    @staticmethod
    def pipeline_start(prompt, steps):
        _print(f"\n{LION} Lion starting...")
        _print(f"   {BOLD}Prompt:{RESET} {prompt}")
        if steps:
            pipeline_str = " -> ".join(
                f"{s.function}({', '.join(str(a) for a in s.args)})"
                for s in steps
            )
            _print(f"   {BOLD}Pipeline:{RESET} {pipeline_str}")
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
        }
        icon = icons.get(name, ">")
        _print(f"\n   {icon} {BOLD}{name.upper()}{RESET}: {description}")

    @staticmethod
    def agent_proposal(num, model, preview):
        preview_clean = preview.replace("\n", " ")[:150]
        _print(f"   +-- Agent {num} ({model}): {DIM}{preview_clean}...{RESET}")

    @staticmethod
    def agent_critique(num, preview):
        preview_clean = preview.replace("\n", " ")[:150]
        _print(f"   |-- Agent {num} critique: {DIM}{preview_clean}...{RESET}")

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
                summary = a.get("summary", "")
                _print(f"   - {name}: {DIM}{summary}{RESET}")

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
