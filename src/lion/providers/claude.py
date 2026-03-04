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

    def __init__(self, model=None, config=None):
        super().__init__(model, config)
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
        system_prompt = self._get_effective_system_prompt(system_prompt)

        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if self.model_override:
            cmd.extend(["--model", self.model_override])
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        env = self._safe_env()

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error=f"Timeout after {self.timeout}s"
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
        """Use claude -p with streaming to make actual file changes.

        Streams output via Display.pair_lead_chunk() so the TUI can show
        progress in real time, while still collecting the full result.

        Args:
            prompt: The implementation prompt
            cwd: Working directory

        Returns:
            AgentResult with response
        """
        from ..display import Display

        impl_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Make the actual code changes. Edit the files directly. "
            "Create new files as needed. Do not just describe what to do - DO it.\n\n"
            "CRITICAL: Do NOT run any 'lion' commands. Do NOT execute example commands "
            "from documentation or proposals. Only write/edit code files."
        )

        cmd = [
            "claude", "-p", impl_prompt,
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]
        if self.model_override:
            cmd.extend(["--model", self.model_override])

        env = self._safe_env()

        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=cwd, env=env,
            )
        except Exception as e:
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error=str(e),
            )

        # Stream stdout line by line, parsing stream-json
        lines_collected = []
        result_entry = None
        try:
            for line in proc.stdout:
                lines_collected.append(line)
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type")
                if msg_type == "assistant":
                    message = entry.get("message", {})
                    for part in message.get("content", []):
                        part_type = part.get("type", "text")
                        text = part.get("text")
                        if text and part_type == "text":
                            Display.pair_lead_chunk(self.name, text)
                        elif part_type == "tool_use":
                            inp = part.get("input", {})
                            tool_name = part.get("name", "")
                            code = ""
                            if tool_name == "Write":
                                code = inp.get("content", "")
                            elif tool_name == "Edit":
                                code = inp.get("new_string", "")
                            if code:
                                Display.pair_lead_chunk(self.name, code)
                elif msg_type == "result":
                    result_entry = entry

            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=time.time() - start,
                success=False, error="Timeout after 1200s",
            )

        duration = time.time() - start

        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            return AgentResult(
                content="", model=self.name, tokens_used=0,
                duration_seconds=duration, success=False,
                error=stderr,
            )

        # Extract result from the stream-json result entry
        if result_entry:
            return AgentResult(
                content=result_entry.get("result", ""),
                model=self.name,
                tokens_used=0,
                duration_seconds=duration,
                success=not result_entry.get("is_error", False),
                error=result_entry.get("result", "") if result_entry.get("is_error") else None,
            )

        # Fallback: try parsing all collected lines as regular JSON
        full_stdout = "".join(lines_collected)
        return self._parse_output(full_stdout, duration)

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
