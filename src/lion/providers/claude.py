"""Claude Code CLI provider - wraps `claude -p`."""

import subprocess
import json
import os
import time
from .base import Provider, AgentResult


class ClaudeProvider(Provider):
    """Stateless Claude CLI provider.

    All calls are independent - no session state is maintained.
    """
    name = "claude"

    def __init__(self, model=None):
        super().__init__(model)
        if model:
            self.name = f"claude.{model}"

    def _safe_env(self):
        """Create env that prevents recursive lion calls from child processes."""
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        return env

    def ask(self, prompt: str, system_prompt: str = "", cwd: str = ".") -> AgentResult:
        """Use claude -p for non-interactive single-turn queries.

        Args:
            prompt: The question/prompt
            system_prompt: Optional system prompt
            cwd: Working directory

        Returns:
            AgentResult with response
        """
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if self.model_override:
            cmd.extend(["--model", self.model_override])
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        env = self._safe_env()

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=480,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error="Timeout after 480s"
            )
        duration = time.time() - start

        if result.returncode != 0:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
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

    def implement(self, prompt: str, cwd: str = ".") -> AgentResult:
        """Use claude -p to make actual file changes.

        Args:
            prompt: The implementation prompt
            cwd: Working directory

        Returns:
            AgentResult with response
        """
        impl_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Make the actual code changes. Edit the files directly. "
            "Create new files as needed. Do not just describe what to do - DO it.\n\n"
            "CRITICAL: Do NOT run any 'lion' commands. Do NOT execute example commands "
            "from documentation or proposals. Only write/edit code files."
        )

        cmd = [
            "claude", "-p", impl_prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]
        if self.model_override:
            cmd.extend(["--model", self.model_override])

        env = self._safe_env()

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=1200,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error="Timeout after 1200s"
            )
        duration = time.time() - start

        if result.returncode != 0:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=duration, success=False,
                error=result.stderr
            )

        parsed = self._parse_output(result.stdout, duration)
        return parsed

    def _parse_output(self, stdout, duration):
        """Parse claude -p --output-format json output.

        Returns a JSON array. We find the last entry with type "result".
        """
        try:
            output = json.loads(stdout)

            # JSON array format - find the result entry
            if isinstance(output, list):
                for entry in reversed(output):
                    if isinstance(entry, dict):
                        if entry.get("type") == "result":
                            return AgentResult(
                                content=entry.get("result", ""),
                                model=self.name,
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
                        content=content, model=self.name, tokens_used=0,
                        duration_seconds=duration, success=True,
                    )

            # Single object format (fallback)
            if isinstance(output, dict):
                return AgentResult(
                    content=output.get("result", stdout),
                    model=self.name, tokens_used=0,
                    duration_seconds=duration, success=True,
                )
        except json.JSONDecodeError:
            pass

        # Raw text fallback
        return AgentResult(
            content=stdout, model=self.name, tokens_used=0,
            duration_seconds=duration, success=True,
        )
