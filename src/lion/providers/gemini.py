"""Gemini CLI provider - wraps `gemini` CLI."""

import subprocess
import json
import os
import time
from .base import Provider, AgentResult


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model=None):
        super().__init__(model)
        if model:
            self.name = f"gemini.{model}"

    @staticmethod
    def _safe_env():
        """Create env that prevents recursive lion calls from child processes."""
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        return env

    def ask(self, prompt, system_prompt="", cwd="."):
        """Use gemini CLI for non-interactive single-turn queries."""
        cmd = ["gemini", "-o", "json"]
        if self.model_override:
            cmd.extend(["-m", self.model_override])
        cmd.append(prompt)

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
        """Use gemini CLI with --yolo to make actual file changes."""
        impl_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Make the actual code changes. Edit the files directly. "
            "Create new files as needed. Do not just describe what to do - DO it.\n\n"
            "CRITICAL: Do NOT run any 'lion' commands. Do NOT execute example commands "
            "from documentation or proposals. Only write/edit code files."
        )

        cmd = ["gemini", "-o", "json", "--yolo"]
        if self.model_override:
            cmd.extend(["-m", self.model_override])
        cmd.append(impl_prompt)

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
                error=result.stderr or f"Exit code {result.returncode}"
            )

        return self._parse_output(result.stdout, duration)

    def _parse_output(self, stdout, duration):
        """Parse gemini -o json output.

        Gemini returns: {"response": "...", "stats": {...}}
        """
        try:
            output = json.loads(stdout)

            if isinstance(output, dict):
                content = output.get("response", "")
                tokens = 0
                stats = output.get("stats", {})
                for model_stats in stats.get("models", {}).values():
                    tokens += model_stats.get("tokens", {}).get("total", 0)

                parsed = AgentResult(
                    content=content,
                    model=self.name,
                    tokens_used=tokens,
                    duration_seconds=duration,
                    success=True,
                )

                if not content.strip():
                    parsed.error = "gemini returned empty response"

                return parsed

        except json.JSONDecodeError:
            pass

        # Raw text fallback
        return AgentResult(
            content=stdout, model=self.name, tokens_used=0,
            duration_seconds=duration, success=True
        )
