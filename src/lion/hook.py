#!/usr/bin/env python3
"""Lion - UserPromptSubmit hook for Claude Code.

Intercepts prompts starting with "lion " and routes them
to the Lion orchestrator. Zero tokens consumed for orchestration.
"""

import sys
import json
import subprocess
import os

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    # Read hook input from stdin (Claude Code sends JSON)
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)  # Not valid JSON, let it through

    # Extract the user's prompt
    prompt = hook_input.get("prompt", "").strip()

    # Check if this is a lion command
    if not prompt.lower().startswith("lion "):
        # Not a lion command - pass through to Claude Code normally
        # IMPORTANT: no stdout output, or it gets added as context
        sys.exit(0)

    # It IS a lion command - extract the actual prompt
    lion_input = prompt[5:].strip()  # Remove "lion " prefix

    # Get working directory from hook context
    cwd = hook_input.get("cwd", os.getcwd())
    session_id = hook_input.get("session_id", "unknown")

    # Set up environment for the lion process
    env = os.environ.copy()
    env["LION_SESSION_ID"] = session_id
    env["LION_CWD"] = cwd
    env["PYTHONPATH"] = SRC_DIR

    # Spawn lion as a detached process
    # Open /dev/tty so lion output goes directly to the terminal
    try:
        tty = open("/dev/tty", "w")
        subprocess.Popen(
            [sys.executable, "-m", "lion", lion_input],
            cwd=cwd,
            env=env,
            stdout=tty,
            stderr=tty,
            start_new_session=True,
        )
    except OSError:
        subprocess.Popen(
            [sys.executable, "-m", "lion", lion_input],
            cwd=cwd,
            env=env,
            start_new_session=True,
        )

    # Block the prompt from reaching Claude
    # JSON output with decision "block" prevents Claude from seeing this prompt
    print(json.dumps({
        "decision": "block",
        "reason": "\U0001f981 Lion is orchestrating this prompt. Watch the terminal for progress.",
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
