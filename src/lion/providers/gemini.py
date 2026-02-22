"""Gemini CLI provider - wraps `gemini` CLI."""

import subprocess
import json
import os
import time
import threading
from .base import Provider, AgentResult

# Class-level rate limiter shared across all GeminiProvider instances.
# Ensures parallel pride agents don't exhaust the API quota.
_gemini_lock = threading.Lock()
_gemini_last_call = 0.0
_GEMINI_MIN_INTERVAL = 4.0  # seconds between calls (15 RPM safe)


def _wait_for_rate_limit():
    """Wait if needed to respect Gemini rate limits."""
    global _gemini_last_call
    with _gemini_lock:
        now = time.time()
        elapsed = now - _gemini_last_call
        if elapsed < _GEMINI_MIN_INTERVAL:
            wait = _GEMINI_MIN_INTERVAL - elapsed
            time.sleep(wait)
        _gemini_last_call = time.time()


class GeminiProvider(Provider):
    name = "gemini"

    # Default to Flash - Pro Preview has severe capacity limits on free tier.
    # Override with gemini.gemini-3-pro-preview if you have a paid plan.
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, model=None):
        super().__init__(model or self.DEFAULT_MODEL)
        if model:
            self.name = f"gemini.{model}"
        self._session_id = None

    def _safe_env(self):
        """Create env that prevents recursive lion calls from child processes
        and passes through the current session ID.
        """
        env = os.environ.copy()
        env["LION_NO_RECURSE"] = "1"
        if self._session_id:
            env["LION_SESSION_ID"] = self._session_id
        return env

    def ask(self, prompt, system_prompt="", cwd=".", resume=True):
        """Use gemini CLI for non-interactive single-turn queries."""
        _wait_for_rate_limit()

        cmd = ["gemini", "-o", "json"]
        if self.model_override:
            cmd.extend(["-m", self.model_override])
        if resume and self._session_id:
            cmd.extend(["--session-id", self._session_id])
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

        parsed = self._parse_output(result.stdout, duration)
        if parsed.session_id:
            self._session_id = parsed.session_id
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

    def ask_fresh(self, prompt, system_prompt="", cwd="."):
        """New session, for parallel propose calls."""
        return self.ask(prompt, system_prompt, cwd, resume=False)

    def implement(self, prompt, cwd="."):
        """Use gemini CLI with --yolo to make actual file changes."""
        _wait_for_rate_limit()

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
        if self._session_id:
            cmd.extend(["--session-id", self._session_id])
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

        parsed = self._parse_output(result.stdout, duration)
        if parsed.session_id:
            self._session_id = parsed.session_id
        return parsed

    def _parse_output(self, stdout, duration):
        """Parse gemini -o json output.

        Gemini returns: {"response": "...", "stats": {...}, "session_id": "..."}
        """
        parsed_session_id = None
        try:
            output = json.loads(stdout)

            if isinstance(output, dict):
                content = output.get("response", "")
                tokens = 0
                stats = output.get("stats", {})
                for model_stats in stats.get("models", {}).values():
                    tokens += model_stats.get("tokens", {}).get("total", 0)
                parsed_session_id = output.get("session_id")

                parsed = AgentResult(
                    content=content,
                    model=self.name,
                    tokens_used=tokens,
                    duration_seconds=duration,
                    success=True,
                    session_id=parsed_session_id,
                )

                if not content.strip():
                    parsed.error = "gemini returned empty response"

                return parsed

        except json.JSONDecodeError:
            pass

        # Raw text fallback
        return AgentResult(
            content=stdout, model=self.name, tokens_used=0,
            duration_seconds=duration, success=True,
            session_id=parsed_session_id,
        )
