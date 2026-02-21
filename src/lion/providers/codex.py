"""OpenAI Codex CLI provider - wraps `codex exec`."""

import subprocess
import json
import os
import time
from .base import Provider, AgentResult


class CodexProvider(Provider):
    name = "codex"

    def __init__(self, model=None):
        super().__init__(model)
        if model:
            self.name = f"codex.{model}"

    @staticmethod
    def _safe_env():
        """Create env that prevents recursive lion calls from child processes."""
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        return env

    def ask(self, prompt, system_prompt="", cwd="."):
        """Use codex exec --json for non-interactive queries."""
        cmd = ["codex", "exec", "--json", "--full-auto", prompt]
        if cwd != ".":
            cmd.extend(["-C", cwd])

        env = self._safe_env()

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=480,
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

        return self._parse_output(result.stdout, duration)

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
        """Use codex exec with full permissions to make file changes."""
        impl_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Make the actual code changes. Edit the files directly. "
            "Create new files as needed. Do not just describe what to do - DO it.\n\n"
            "CRITICAL: Do NOT run any 'lion' commands. Do NOT execute example commands "
            "from documentation or proposals. Only write/edit code files."
        )

        cmd = [
            "codex", "exec", "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            impl_prompt,
        ]
        if cwd != ".":
            cmd.extend(["-C", cwd])

        env = self._safe_env()

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=1200,
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
                error=result.stderr or f"Exit code {result.returncode}"
            )

        return self._parse_output(result.stdout, duration)

    def _parse_output(self, stdout, duration):
        """Parse codex exec --json JSONL output.

        Each line is a JSON object. We look for:
        - type "item.completed" with item.text for the response
        - type "turn.completed" with usage for token counts
        """
        content = ""
        tokens = 0

        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "item.completed":
                item = entry.get("item", {})
                text = item.get("text", "")
                if text:
                    content = text if not content else content + "\n" + text

            elif entry.get("type") == "turn.completed":
                usage = entry.get("usage", {})
                tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        if not content.strip():
            return AgentResult(
                content=content, model=self.name, tokens_used=tokens,
                duration_seconds=duration, success=True,
                error="codex returned empty response"
            )

        return AgentResult(
            content=content,
            model=self.name,
            tokens_used=tokens,
            duration_seconds=duration,
            success=True,
        )
