#!/usr/bin/env python3
"""Lion - UserPromptSubmit hook for Claude Code.

Intercepts prompts starting with "lion " and routes them
to the Lion orchestrator. Runs Lion synchronously, then
injects the result as context for Claude to relay.
"""

import sys
import json
import subprocess
import os

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def extract_summary(stdout):
    """Extract the LION_SUMMARY JSON from Lion's stdout."""
    if not stdout:
        return None
    for line in stdout.split("\n"):
        if line.startswith("LION_SUMMARY:"):
            try:
                return json.loads(line[len("LION_SUMMARY:"):])
            except json.JSONDecodeError:
                continue
    return None


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    raw_prompt = hook_input.get("prompt", "").strip()

    # Extract user text - IDE may prepend XML tags like <ide_opened_file>
    lion_line = None
    for line in raw_prompt.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("lion "):
            lion_line = stripped
            break

    if not lion_line:
        sys.exit(0)

    lion_input = lion_line[5:].strip()
    cwd = hook_input.get("cwd", os.getcwd())
    session_id = hook_input.get("session_id", "unknown")

    env = os.environ.copy()
    env["LION_SESSION_ID"] = session_id
    env["LION_CWD"] = cwd
    env["PYTHONPATH"] = SRC_DIR

    try:
        result = subprocess.run(
            [sys.executable, "-m", "lion", lion_input],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        summary_data = extract_summary(result.stdout)

        if summary_data:
            reason = summary_data.get("summary", "Lion voltooid")
        elif result.returncode != 0:
            reason = f"Lion fout (exit code {result.returncode})"
        else:
            reason = "Lion voltooid"

    except Exception as e:
        reason = f"Lion kon niet starten: {str(e)}"

    # Exit 0 + stdout = context injected into Claude's conversation
    context = (
        f"<lion-result>\n"
        f"The user's prompt was a Lion command that has already been executed.\n"
        f"Do NOT process this prompt yourself. Instead, tell the user what Lion did.\n"
        f"Lion result: {reason}\n"
        f"</lion-result>"
    )
    print(context)
    sys.exit(0)


if __name__ == "__main__":
    main()
