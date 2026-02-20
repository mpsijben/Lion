"""Escalation - User interaction when agent is stuck or needs input.

Handles communication with the user during a Lion run via /dev/tty
to bypass stdout redirection.
"""

import sys


def _read_tty(prompt_text: str) -> str:
    """Read input from /dev/tty to bypass stdout redirection."""
    try:
        with open("/dev/tty", "w") as tty_out:
            tty_out.write(prompt_text)
            tty_out.flush()
        with open("/dev/tty", "r") as tty_in:
            return tty_in.readline().strip()
    except OSError:
        raise RuntimeError(
            "Cannot read from /dev/tty - Lion requires an interactive terminal for escalation. "
            "Run Lion in an interactive shell, not in a CI environment or piped context."
        )


def _print_tty(message: str):
    """Print to /dev/tty to bypass stdout redirection."""
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(message + "\n")
            tty.flush()
    except OSError:
        print(message, file=sys.stderr)


class Escalation:
    """Handles user interaction when agents need help."""

    @staticmethod
    def ask_choice(question: str, options: list[str]) -> int:
        """Present a choice to the user, return the selected index (0-based)."""
        _print_tty("\n\U0001f981 Lion needs your input:\n")
        _print_tty(f"   {question}\n")
        for i, option in enumerate(options, 1):
            _print_tty(f"   [{i}] {option}")
        _print_tty("")

        while True:
            try:
                choice = _read_tty("   Your choice: ")
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return idx
            except (ValueError, RuntimeError) as e:
                if isinstance(e, RuntimeError):
                    raise
            _print_tty(f"   Please enter a number between 1 and {len(options)}")

    @staticmethod
    def ask_text(question: str) -> str:
        """Ask the user for free-text input."""
        _print_tty("\n\U0001f981 Lion needs your input:\n")
        _print_tty(f"   {question}\n")
        return _read_tty("   > ")

    @staticmethod
    def notify(message: str):
        """Display a notification to the user."""
        _print_tty(f"\n\U0001f981 {message}")

    @staticmethod
    def agent_stuck(agent_name: str, error: str, retries_left: int = 0) -> str:
        """Handle agent stuck scenario.

        Returns one of:
        - "hint:<user's hint text>"
        - "skip"
        - "takeover"
        - "retry"
        """
        _print_tty(f"\n\U0001f981 Agent '{agent_name}' is stuck.\n")
        _print_tty(f"   Error: {error}\n")

        options = ["Give a hint to the agent"]
        if retries_left > 0:
            options.append(f"Retry ({retries_left} attempts remaining)")
        options.append("Skip this task")
        options.append("Take over in Claude Code")

        choice = Escalation.ask_choice("How should we proceed?", options)

        if choice == 0:
            hint = Escalation.ask_text("Your hint:")
            return f"hint:{hint}"
        elif retries_left > 0 and choice == 1:
            return "retry"
        elif choice == len(options) - 2:
            return "skip"
        else:
            return "takeover"

    @staticmethod
    def no_consensus(proposals: list[dict], max_rounds_reached: bool = False) -> str:
        """Handle no-consensus scenario among pride agents.

        Returns one of:
        - "use_proposal:<index>"
        - "retry"
        - "takeover"
        """
        _print_tty("\n\U0001f981 The pride could not reach consensus.\n")

        if max_rounds_reached:
            _print_tty("   Maximum deliberation rounds reached.\n")

        options = []
        for i, p in enumerate(proposals):
            summary = p.get("content", "")[:100]
            if len(p.get("content", "")) > 100:
                summary += "..."
            agent = p.get("agent", f"Agent {i+1}")
            model = p.get("model", "unknown")
            options.append(f"{agent} ({model}): {summary}")

        options.append("Let the pride try one more round")
        options.append("Take over manually in Claude Code")

        choice = Escalation.ask_choice("Which approach should we use?", options)

        if choice < len(proposals):
            return f"use_proposal:{choice}"
        elif choice == len(proposals):
            return "retry"
        else:
            return "takeover"

    @staticmethod
    def confirm_action(action: str, details: str = "") -> bool:
        """Ask user to confirm a potentially destructive action.

        Returns True if confirmed, False otherwise.
        """
        _print_tty("\n\U0001f981 Confirmation required:\n")
        _print_tty(f"   Action: {action}")
        if details:
            _print_tty(f"   Details: {details}")
        _print_tty("")

        choice = Escalation.ask_choice("Proceed?", ["Yes, continue", "No, cancel"])
        return choice == 0

    @staticmethod
    def low_confidence(context: str, confidence_reason: str) -> str:
        """Handle low confidence scenario.

        Returns one of:
        - "proceed"
        - "hint:<user's guidance>"
        - "takeover"
        """
        _print_tty("\n\U0001f981 Agent has low confidence:\n")
        _print_tty(f"   Context: {context}")
        _print_tty(f"   Reason: {confidence_reason}\n")

        choice = Escalation.ask_choice(
            "How should we proceed?",
            [
                "Proceed anyway",
                "Provide guidance",
                "Take over in Claude Code"
            ]
        )

        if choice == 0:
            return "proceed"
        elif choice == 1:
            guidance = Escalation.ask_text("Your guidance:")
            return f"hint:{guidance}"
        else:
            return "takeover"
