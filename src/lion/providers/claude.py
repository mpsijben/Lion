"""Claude Code CLI provider - wraps `claude -p`."""

import subprocess
import json
import time
from .base import Provider, AgentResult


class ClaudeProvider(Provider):
    name = "claude"

    def ask(self, prompt, system_prompt="", cwd="."):
        """Use claude -p for non-interactive single-turn queries."""
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=300
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                content="", model="claude", tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error="Timeout after 300s"
            )
        duration = time.time() - start

        if result.returncode != 0:
            return AgentResult(
                content="", model="claude", tokens_used=0,
                duration_seconds=duration, success=False,
                error=result.stderr or f"Exit code {result.returncode}"
            )

        parsed = self._parse_output(result.stdout, duration)

        # Flag empty responses as potential issues
        if parsed.success and not parsed.content.strip():
            parsed.error = "claude -p returned empty response"

        return parsed

    def ask_with_files(self, prompt, files, system_prompt="", cwd="."):
        """Include file contents in the prompt."""
        file_contents = []
        for f in files:
            try:
                with open(f, "r") as fh:
                    file_contents.append(f"--- {f} ---\n{fh.read()}")
            except Exception:
                file_contents.append(f"--- {f} --- (could not read)")

        full_prompt = f"{prompt}\n\nFILES:\n" + "\n".join(file_contents)
        return self.ask(full_prompt, system_prompt, cwd)

    def implement(self, prompt, cwd="."):
        """Use claude -p to make actual file changes."""
        impl_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Make the actual code changes. Edit the files directly. "
            "Create new files as needed. Do not just describe what to do - DO it."
        )

        cmd = [
            "claude", "-p", impl_prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=600
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                content="", model="claude", tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error="Timeout after 600s"
            )
        duration = time.time() - start

        if result.returncode != 0:
            return AgentResult(
                content="", model="claude", tokens_used=0,
                duration_seconds=duration, success=False,
                error=result.stderr
            )

        return self._parse_output(result.stdout, duration)

    def _parse_output(self, stdout, duration):
        """Parse claude -p --output-format json output.

        Returns a JSON array. We find the last entry with type "result".
        """
        try:
            output = json.loads(stdout)

            # JSON array format - find the result entry
            if isinstance(output, list):
                for entry in reversed(output):
                    if isinstance(entry, dict) and entry.get("type") == "result":
                        return AgentResult(
                            content=entry.get("result", ""),
                            model="claude",
                            tokens_used=0,
                            duration_seconds=duration,
                            success=not entry.get("is_error", False),
                            error=entry.get("result", "") if entry.get("is_error") else None,
                        )
                # No result entry found, use last entry's content
                if output:
                    last = output[-1]
                    content = last.get("result", last.get("content", str(last)))
                    return AgentResult(
                        content=content, model="claude", tokens_used=0,
                        duration_seconds=duration, success=True
                    )

            # Single object format (fallback)
            if isinstance(output, dict):
                return AgentResult(
                    content=output.get("result", stdout),
                    model="claude", tokens_used=0,
                    duration_seconds=duration, success=True
                )
        except json.JSONDecodeError:
            pass

        # Raw text fallback
        return AgentResult(
            content=stdout, model="claude", tokens_used=0,
            duration_seconds=duration, success=True
        )
